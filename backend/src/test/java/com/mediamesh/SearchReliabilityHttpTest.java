package com.mediamesh;

import com.mediamesh.identity.*;
import com.mediamesh.media.*;
import com.mediamesh.observability.*;
import com.sun.net.httpserver.HttpServer;
import io.github.resilience4j.bulkhead.BulkheadRegistry;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;
import io.micrometer.core.instrument.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.*;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.test.context.*;
import org.springframework.test.web.servlet.MockMvc;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest({SearchController.class,IdentityController.class})
@Import({MediaMeshSecurityConfiguration.class,ApiErrors.class,SearchSliFilter.class,SearchSliMetrics.class,
        MlSearchClient.class,MlResilienceConfiguration.class,SearchReliabilityHttpTest.Metrics.class})
class SearchReliabilityHttpTest {
    @TestConfiguration static class Metrics {@Bean MeterRegistry metrics(){return new SimpleMeterRegistry();}}
    static final HttpServer stub;
    static final ExecutorService handlers=Executors.newCachedThreadPool();
    static final AtomicInteger status=new AtomicInteger(200);
    static final AtomicReference<String> responseBody=new AtomicReference<>("{\"matches\":[]}");
    static volatile CountDownLatch entered=new CountDownLatch(0),release=new CountDownLatch(0);
    static {
        try {
            stub=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);stub.setExecutor(handlers);
            stub.createContext("/internal/",exchange->{
                entered.countDown();
                try {
                    release.await(5,TimeUnit.SECONDS);
                    byte[] body=responseBody.get().getBytes(StandardCharsets.UTF_8);
                    exchange.sendResponseHeaders(status.get(),body.length);
                    try(var output=exchange.getResponseBody()){output.write(body);}
                } catch(InterruptedException e){Thread.currentThread().interrupt();}
                finally {exchange.close();}
            });stub.start();
        } catch(Exception e){throw new RuntimeException(e);}
    }
    @DynamicPropertySource static void properties(DynamicPropertyRegistry properties){
        properties.add("mediamesh.ml.url",()->"http://127.0.0.1:"+stub.getAddress().getPort());
    }
    @Autowired MockMvc mvc;
    @Autowired MeterRegistry metrics;
    @Autowired CircuitBreakerRegistry breakers;
    @Autowired BulkheadRegistry bulkheads;
    @MockBean JwtDecoder decoder;
    @MockBean IdentityService identities;
    @MockBean AssetRepository assets;
    @BeforeEach void setup(){
        status.set(200);release=new CountDownLatch(0);entered=new CountDownLatch(0);
        responseBody.set("{\"matches\":[]}");
        breakers.circuitBreaker("mlSearch").reset();
        var jwt=Jwt.withTokenValue("researcher").header("alg","RS256").subject("researcher").build();
        var user=new IdentityService.User(UUID.randomUUID(),"test@example.org","Test",List.of("RESEARCHER"),false,List.of(),"NONE");
        when(decoder.decode(anyString())).thenReturn(jwt);when(identities.authenticate(any())).thenReturn(user);
        when(identities.user(any())).thenReturn(user);
        when(assets.eligible(any())).thenReturn(List.of(UUID.randomUUID()));
    }
    @AfterAll static void close(){release.countDown();stub.stop(0);handlers.shutdownNow();}
    org.springframework.test.web.servlet.ResultActions search() throws Exception {
        return mvc.perform(post("/api/search").header("Authorization","Bearer researcher")
                .contentType("application/json").content("{\"query\":\"elephants\"}"));
    }
    double count(String name){return metrics.get(name).counter().count();}
    @Test void emptySearchIsGoodAndInvalidRequestsAreExcluded() throws Exception {
        double before=count("mediamesh.search.requests"),good=count("mediamesh.search.good");
        search().andExpect(status().isOk()).andExpect(jsonPath("$.results").isEmpty());
        mvc.perform(post("/api/search").contentType("application/json").content("{}")).andExpect(status().isUnauthorized());
        mvc.perform(post("/api/search").header("Authorization","Bearer researcher").contentType("application/json").content("{}")).andExpect(status().isBadRequest());
        var user=new IdentityService.User(UUID.randomUUID(),"","",List.of(),false,List.of(),"NONE");
        when(identities.authenticate(any())).thenReturn(user);
        search().andExpect(status().isForbidden());
        assertThat(count("mediamesh.search.requests")-before).isEqualTo(1);
        assertThat(count("mediamesh.search.good")-good).isEqualTo(1);
    }
    @Test void searchAndRelatedApplyTheInclusiveScoreCutoff() throws Exception {
        var video=UUID.randomUUID();
        var image=UUID.randomUUID();
        var weakImage=UUID.randomUUID();
        when(assets.eligible(any())).thenReturn(List.of(video,image,weakImage));
        var owner=UUID.randomUUID();
        when(assets.findById(video)).thenReturn(Optional.of(new Asset(video,owner,"video",
                MediaType.video,"Untitled clip",null,null,null,null,null,null,AssetStatus.READY)));
        when(assets.findById(image)).thenReturn(Optional.of(new Asset(image,owner,"image",
                MediaType.image,"Untitled photo",null,null,null,null,null,null,AssetStatus.READY)));
        when(assets.findById(weakImage)).thenReturn(Optional.of(new Asset(weakImage,owner,"weak-image",
                MediaType.image,"Elephants", "Elephants",null,null,null,null,null,AssetStatus.READY)));
        when(assets.generatedDescription(video)).thenReturn("A bear walking across snowy ground.");
        responseBody.set("""
                {"matches":[
                    {"assetId":"%s","score":0.82,"frameTimestampSeconds":4.0},
                    {"assetId":"%s","score":0.67},
                    {"assetId":"%s","score":0.669}
                ]}
                """.formatted(video,image,weakImage));

        search().andExpect(status().isOk())
                .andExpect(jsonPath("$.results.length()").value(2))
                .andExpect(jsonPath("$.results[0].assetId").value(video.toString()))
                .andExpect(jsonPath("$.results[0].generatedDescription")
                        .value("A bear walking across snowy ground."))
                .andExpect(jsonPath("$.results[1].assetId").value(image.toString()));
        var source=UUID.randomUUID();
        when(assets.findById(source)).thenReturn(Optional.of(new Asset(source,owner,"source",
                MediaType.image,"Source",null,null,null,null,null,null,AssetStatus.READY)));
        mvc.perform(post("/api/assets/"+source+"/similar")
                .header("Authorization","Bearer researcher"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.results.length()").value(2))
                .andExpect(jsonPath("$.results[1].assetId").value(image.toString()));
        verify(assets,never()).findById(weakImage);
    }
    @Test void circuitRejectionsAreStructuredAndConsumeBudget() throws Exception {
        double before=count("mediamesh.search.bad");status.set(503);
        for(int i=0;i<6;i++) search().andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error.code").value("ML_SEARCH_UNAVAILABLE"));
        assertThat(count("mediamesh.search.bad")-before).isEqualTo(6);
        assertThat(metrics.get("mediamesh.search.failures").tag("category","circuit_open").counter().count()).isGreaterThanOrEqualTo(1);
    }
    @Test void bulkheadRejectsImmediatelyWhileMeStillWorks() throws Exception {
        entered=new CountDownLatch(5);release=new CountDownLatch(1);
        double bad=count("mediamesh.search.bad"),rejected=count("mediamesh.ml.bulkhead.rejected");
        var pool=Executors.newFixedThreadPool(5);
        try {
            var pending=new ArrayList<Future<?>>();
            for(int i=0;i<5;i++) pending.add(pool.submit(()->{try {search().andExpect(status().isOk());}catch(Exception e){throw new RuntimeException(e);}}));
            assertThat(entered.await(1,TimeUnit.SECONDS)).isTrue();
            long started=System.nanoTime();
            search().andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.code").value("ML_SEARCH_BUSY"));
            mvc.perform(get("/api/me").header("Authorization","Bearer researcher")).andExpect(status().isOk());
            assertThat(System.nanoTime()-started).isLessThan(TimeUnit.SECONDS.toNanos(1));
            assertThat(count("mediamesh.search.bad")-bad).isEqualTo(1);
            assertThat(count("mediamesh.ml.bulkhead.rejected")-rejected).isEqualTo(1);
            assertThat(breakers.circuitBreaker("mlSearch").getMetrics().getNumberOfBufferedCalls()).isZero();
            release.countDown();for(var result:pending) result.get(2,TimeUnit.SECONDS);
            assertThat(bulkheads.bulkhead("mlSearch").getMetrics().getAvailableConcurrentCalls()).isEqualTo(5);
        } finally {release.countDown();pool.shutdownNow();}
    }
    @Test void timeoutReturns503AndIsCountedExactlyOnce() throws Exception {
        release=new CountDownLatch(1);
        double before=count("mediamesh.search.bad");
        try {search().andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.code").value("ML_SEARCH_UNAVAILABLE"));}
        finally {release.countDown();}
        assertThat(count("mediamesh.search.bad")-before).isEqualTo(1);
        assertThat(metrics.get("mediamesh.search.failures").tag("category","timeout").counter().count()).isGreaterThanOrEqualTo(1);
    }
}
