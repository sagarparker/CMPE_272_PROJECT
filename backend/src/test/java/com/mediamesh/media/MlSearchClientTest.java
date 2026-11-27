package com.mediamesh.media;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import io.github.resilience4j.bulkhead.*;
import io.github.resilience4j.circuitbreaker.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.net.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.*;
import static org.assertj.core.api.Assertions.*;

class MlSearchClientTest {
    HttpServer server;
    ExecutorService handlers;
    AtomicInteger calls=new AtomicInteger(),active=new AtomicInteger(),maximum=new AtomicInteger();
    AtomicInteger status=new AtomicInteger(200);
    volatile CountDownLatch entered=new CountDownLatch(0),release=new CountDownLatch(0);
    SimpleMeterRegistry metrics=new SimpleMeterRegistry();
    CircuitBreakerRegistry breakers;
    BulkheadRegistry bulkheads;
    MlSearchClient client;
    AtomicReference<Instant> now=new AtomicReference<>(Instant.parse("2026-01-01T00:00:00Z"));
    Clock clock=new Clock() {
        public ZoneId getZone(){return ZoneOffset.UTC;}
        public Clock withZone(ZoneId zone){return this;}
        public Instant instant(){return now.get();}
    };
    @BeforeEach void setup() throws Exception {
        server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        handlers=Executors.newCachedThreadPool();server.setExecutor(handlers);
        server.createContext("/internal/search",exchange -> {
            calls.incrementAndGet();maximum.accumulateAndGet(active.incrementAndGet(),Math::max);entered.countDown();
            try {
                release.await(5,TimeUnit.SECONDS);
                byte[] body=(status.get()==200 ? "{\"matches\":[]}" : "{\"error\":{\"code\":\"INVALID_INPUT\"}}" ).getBytes();
                exchange.sendResponseHeaders(status.get(),body.length);
                try(var out=exchange.getResponseBody()){out.write(body);}
            } catch (InterruptedException e) {Thread.currentThread().interrupt();}
            finally {active.decrementAndGet();exchange.close();}
        });
        server.start();
        var config=CircuitBreakerConfig.custom().slidingWindowSize(10).minimumNumberOfCalls(5)
                .failureRateThreshold(50).waitDurationInOpenState(Duration.ofSeconds(10))
                .permittedNumberOfCallsInHalfOpenState(2).ignoreExceptions(MlSearchClient.InvalidSearchInput.class).build();
        breakers=CircuitBreakerRegistry.of(config);
        breakers.circuitBreaker("mlSearch");
        breakers.replace("mlSearch",new io.github.resilience4j.circuitbreaker.internal.CircuitBreakerStateMachine("mlSearch",config,clock));
        bulkheads=BulkheadRegistry.of(BulkheadConfig.custom().maxConcurrentCalls(5).maxWaitDuration(Duration.ZERO).build());
        client=client(Duration.ofSeconds(2));
    }
    MlSearchClient client(Duration timeout) {
        return new MlSearchClient(new ObjectMapper(),breakers,bulkheads,metrics,
                URI.create("http://127.0.0.1:"+server.getAddress().getPort()),timeout,Duration.ofMillis(200));
    }
    @AfterEach void close(){release.countDown();server.stop(0);handlers.shutdownNow();metrics.close();}
    @Test void breakerOpensFailsFastAndClosesAfterRecoveryProbes() throws Exception {
        var breaker=breakers.circuitBreaker("mlSearch");
        assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.CLOSED);
        status.set(503);
        for(int i=0;i<5;i++) assertThatThrownBy(()->client.search(Map.of("query","elephants"))).isInstanceOf(SearchFailure.class);
        assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.OPEN);
        int before=calls.get();
        assertThatThrownBy(()->client.search(Map.of())).isInstanceOfSatisfying(SearchFailure.class,
                e->assertThat(e.category()).isEqualTo("circuit_open"));
        assertThat(calls.get()).isEqualTo(before);
        status.set(200);
        // Advance time, without forcing HALF_OPEN or sleeping on the real clock.
        now.updateAndGet(instant -> instant.plusSeconds(11));
        assertThat(client.search(Map.of()).matches()).isEmpty();
        assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.HALF_OPEN);
        client.search(Map.of());
        assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.CLOSED);
    }
    @Test void invalidInputDoesNotTripBreakerAndPermitsAreReleased() {
        status.set(400);
        for(int i=0;i<6;i++) assertThatThrownBy(()->client.search(Map.of())).isInstanceOf(MlSearchClient.InvalidSearchInput.class);
        assertThat(breakers.circuitBreaker("mlSearch").getMetrics().getNumberOfBufferedCalls()).isZero();
        assertThat(bulkheads.bulkhead("mlSearch").getMetrics().getAvailableConcurrentCalls()).isEqualTo(5);
    }
    @Test void timeoutIsBoundedAndReleasesPermit() throws Exception {
        release=new CountDownLatch(1);entered=new CountDownLatch(1);
        client=client(Duration.ofMillis(200));
        long started=System.nanoTime();
        assertThatThrownBy(()->client.search(Map.of())).isInstanceOfSatisfying(SearchFailure.class,
                e->assertThat(e.category()).isEqualTo("timeout"));
        assertThat(Duration.ofNanos(System.nanoTime()-started)).isLessThan(Duration.ofSeconds(1));
        assertThat(metrics.get("mediamesh.ml.search.timeouts").counter().count()).isEqualTo(1);
        assertThat(bulkheads.bulkhead("mlSearch").getMetrics().getAvailableConcurrentCalls()).isEqualTo(5);
    }
    @Test void fiveCallsHoldPermitsAndTwentyExcessCallsNeverReachBreaker() throws Exception {
        release=new CountDownLatch(1);entered=new CountDownLatch(5);
        var pool=Executors.newFixedThreadPool(5);
        try {
            var pending=new ArrayList<Future<?>>();
            for(int i=0;i<5;i++) pending.add(pool.submit(()->client.search(Map.of())));
            assertThat(entered.await(1,TimeUnit.SECONDS)).isTrue();
            for(int i=0;i<20;i++) assertThatThrownBy(()->client.search(Map.of())).isInstanceOfSatisfying(SearchFailure.class,
                    e->assertThat(e.category()).isEqualTo("bulkhead_full"));
            assertThat(calls.get()).isEqualTo(5);assertThat(maximum.get()).isEqualTo(5);
            assertThat(breakers.circuitBreaker("mlSearch").getMetrics().getNumberOfBufferedCalls()).isZero();
            release.countDown();for(var result:pending) result.get(2,TimeUnit.SECONDS);
            assertThat(bulkheads.bulkhead("mlSearch").getMetrics().getAvailableConcurrentCalls()).isEqualTo(5);
            assertThat(breakers.circuitBreaker("mlSearch").getMetrics().getNumberOfSuccessfulCalls()).isEqualTo(5);
        } finally {release.countDown();pool.shutdownNow();}
    }
}
