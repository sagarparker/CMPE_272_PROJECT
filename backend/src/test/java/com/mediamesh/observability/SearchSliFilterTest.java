package com.mediamesh.observability;

import io.micrometer.core.instrument.*;
import io.micrometer.core.instrument.simple.*;
import jakarta.servlet.*;
import org.junit.jupiter.api.*;
import org.springframework.mock.web.*;
import java.time.Duration;
import static org.assertj.core.api.Assertions.*;

class SearchSliFilterTest {
    private final MockClock clock=new MockClock();
    private final SimpleMeterRegistry registry=new SimpleMeterRegistry(SimpleConfig.DEFAULT,clock);
    private final SearchSliFilter filter=new SearchSliFilter(new SearchSliMetrics(registry));
    private MockHttpServletRequest request() {return new MockHttpServletRequest("POST","/api/search");}
    private double count(String name) {return registry.get(name).counter().count();}
    private void respond(int status,Duration latency,String category) throws Exception {
        var request=request();
        filter.doFilter(request,new MockHttpServletResponse(),(req,res) -> {
            clock.add(latency);
            req.setAttribute(SearchSliMetrics.FAILURE_ATTRIBUTE,category);
            ((MockHttpServletResponse)res).setStatus(status);
        });
    }
    @Test void exactlyTwoSecondsIsGoodAndOneNanosecondOverIsBad() throws Exception {
        respond(200,Duration.ofSeconds(2),null);
        respond(200,Duration.ofSeconds(2).plusNanos(1),null);
        assertThat(count("mediamesh.search.requests")).isEqualTo(2);
        assertThat(count("mediamesh.search.good")).isEqualTo(1);
        assertThat(count("mediamesh.search.bad")).isEqualTo(1);
        assertThat(registry.get("mediamesh.search.duration").timer().count()).isEqualTo(2);
        assertThat(registry.get("mediamesh.search.failures").tag("category","slow").counter().count()).isEqualTo(1);
    }
    @Test void serverTimeoutBreakerBulkheadAndRateLimitFailuresAreBad() throws Exception {
        respond(500,Duration.ZERO,null);
        respond(503,Duration.ofMillis(1500),"timeout");
        respond(503,Duration.ZERO,"circuit_open");
        respond(503,Duration.ZERO,"bulkhead_full");
        respond(429,Duration.ZERO,null);
        assertThat(count("mediamesh.search.requests")).isEqualTo(5);
        assertThat(count("mediamesh.search.bad")).isEqualTo(5);
        assertThat(count("mediamesh.search.good")).isZero();
    }
    @Test void invalidClientAndAuthenticationResponsesAreExcluded() throws Exception {
        for (int status:new int[]{400,401,403,413,415,422}) respond(status,Duration.ofSeconds(3),null);
        assertThat(count("mediamesh.search.requests")).isZero();
        assertThat(registry.get("mediamesh.search.duration").timer().count()).isZero();
    }
    @Test void emptySuccessfulResponseIsGood() throws Exception {
        respond(200,Duration.ofMillis(5),null);
        assertThat(count("mediamesh.search.good")).isEqualTo(1);
    }
    @Test void unhandledFailureCountsOnceEvenIfStatusIsNotYetChanged() throws Exception {
        var request=request();var response=new MockHttpServletResponse();
        assertThatThrownBy(() -> filter.doFilter(request,response,(req,res) -> {
            throw new ServletException("Unexpected failure");
        })).isInstanceOf(ServletException.class);
        request.setDispatcherType(DispatcherType.ERROR);
        filter.doFilter(request,response,(req,res) -> response.setStatus(500));
        assertThat(count("mediamesh.search.requests")).isEqualTo(1);
        assertThat(count("mediamesh.search.bad")).isEqualTo(1);
    }
    @Test void otherRoutesAreNotMeasured() throws Exception {
        filter.doFilter(new MockHttpServletRequest("GET","/api/me"),new MockHttpServletResponse(),(req,res)->{});
        filter.doFilter(new MockHttpServletRequest("POST","/api/assets/id/similar"),new MockHttpServletResponse(),(req,res)->{});
        assertThat(count("mediamesh.search.requests")).isZero();
    }
}
