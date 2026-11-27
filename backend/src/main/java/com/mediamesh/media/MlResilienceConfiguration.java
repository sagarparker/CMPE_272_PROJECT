package com.mediamesh.media;

import io.github.resilience4j.bulkhead.*;
import io.github.resilience4j.circuitbreaker.*;
import io.github.resilience4j.micrometer.tagged.*;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;

@Configuration
public class MlResilienceConfiguration {
    @Bean
    CircuitBreakerRegistry mlCircuitBreakers(MeterRegistry metrics,
            @Value("${resilience4j.circuitbreaker.instances.mlSearch.slidingWindowType}") CircuitBreakerConfig.SlidingWindowType type,
            @Value("${resilience4j.circuitbreaker.instances.mlSearch.slidingWindowSize}") int window,
            @Value("${resilience4j.circuitbreaker.instances.mlSearch.minimumNumberOfCalls}") int minimum,
            @Value("${resilience4j.circuitbreaker.instances.mlSearch.failureRateThreshold}") float threshold,
            @Value("${resilience4j.circuitbreaker.instances.mlSearch.waitDurationInOpenState}") Duration wait,
            @Value("${resilience4j.circuitbreaker.instances.mlSearch.permittedNumberOfCallsInHalfOpenState}") int probes) {
        var config=CircuitBreakerConfig.custom().slidingWindowType(type).slidingWindowSize(window)
                .minimumNumberOfCalls(minimum).failureRateThreshold(threshold)
                .waitDurationInOpenState(wait).permittedNumberOfCallsInHalfOpenState(probes)
                .ignoreExceptions(MlSearchClient.InvalidSearchInput.class).build();
        var registry=CircuitBreakerRegistry.of(config);
        TaggedCircuitBreakerMetrics.ofCircuitBreakerRegistry(registry).bindTo(metrics);
        registry.circuitBreaker("mlSearch");
        return registry;
    }
    @Bean
    BulkheadRegistry mlBulkheads(MeterRegistry metrics,
            @Value("${resilience4j.bulkhead.instances.mlSearch.maxConcurrentCalls}") int calls,
            @Value("${resilience4j.bulkhead.instances.mlSearch.maxWaitDuration}") Duration wait) {
        var registry=BulkheadRegistry.of(BulkheadConfig.custom().maxConcurrentCalls(calls).maxWaitDuration(wait).build());
        TaggedBulkheadMetrics.ofBulkheadRegistry(registry).bindTo(metrics);
        var bulkhead=registry.bulkhead("mlSearch");
        var rejected=metrics.counter("mediamesh.ml.bulkhead.rejected");
        bulkhead.getEventPublisher().onCallRejected(event -> rejected.increment());
        metrics.gauge("mediamesh.ml.bulkhead.in.use",bulkhead,
                b -> b.getMetrics().getMaxAllowedConcurrentCalls()-b.getMetrics().getAvailableConcurrentCalls());
        return registry;
    }
}
