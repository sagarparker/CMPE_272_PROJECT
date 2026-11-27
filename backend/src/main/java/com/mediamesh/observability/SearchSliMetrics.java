package com.mediamesh.observability;

import io.micrometer.core.instrument.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Component;

@Component
public class SearchSliMetrics {
    public static final String FAILURE_ATTRIBUTE = SearchSliMetrics.class.getName()+".failure";
    public static final long GOOD_THRESHOLD_NANOS = Duration.ofSeconds(2).toNanos();
    private static final Set<Integer> EXCLUDED = Set.of(400,401,403,413,415,422);
    private final MeterRegistry registry;
    private final Counter requests;
    private final Counter good;
    private final Counter bad;
    private final io.micrometer.core.instrument.Timer duration;
    private final Map<String,Counter> failures = new HashMap<>();

    public SearchSliMetrics(MeterRegistry registry) {
        this.registry=registry;
        requests=registry.counter("mediamesh.search.requests");
        good=registry.counter("mediamesh.search.good");
        bad=registry.counter("mediamesh.search.bad");
        duration=io.micrometer.core.instrument.Timer.builder("mediamesh.search.duration")
                .serviceLevelObjectives(Duration.ofSeconds(2)).register(registry);
        for (String category : List.of("slow","timeout","circuit_open","bulkhead_full","dependency","server_error","unexpected_response"))
            failures.put(category,registry.counter("mediamesh.search.failures","category",category));
    }
    public long now() { return registry.config().clock().monotonicTime(); }
    public void record(int status,long elapsed,String category,boolean unhandled) {
        // Only these responses intentionally identify invalid/unauthorized client requests.
        if (!unhandled && EXCLUDED.contains(status)) return;
        requests.increment();
        duration.record(elapsed,TimeUnit.NANOSECONDS);
        if (!unhandled && status==200 && elapsed<=GOOD_THRESHOLD_NANOS) {
            good.increment();
        } else {
            bad.increment();
            String failure=category;
            if (!failures.containsKey(failure))
                failure=unhandled || status>=500 ? "server_error" : status==200 ? "slow" : "unexpected_response";
            failures.get(failure).increment();
        }
    }
}
