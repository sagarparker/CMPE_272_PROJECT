package com.mediamesh.media;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.resilience4j.bulkhead.*;
import io.github.resilience4j.circuitbreaker.*;
import io.micrometer.core.instrument.*;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
public class MlSearchClient {
    public record Match(UUID assetId,double score,Double frameTimestampSeconds) {}
    public record Matches(List<Match> matches) {}
    public static class InvalidSearchInput extends ResponseStatusException {
        InvalidSearchInput() {super(HttpStatus.BAD_REQUEST,"Query exceeds supported model input");}
    }
    private final HttpClient http;
    private final ObjectMapper json;
    private final URI base;
    private final Duration timeout;
    private final CircuitBreaker breaker;
    private final Bulkhead bulkhead;
    private final Counter timeouts;

    public MlSearchClient(ObjectMapper json,CircuitBreakerRegistry breakers,BulkheadRegistry bulkheads,
            MeterRegistry metrics,@Value("${mediamesh.ml.url}") URI base,
            @Value("${mediamesh.ml.request-timeout}") Duration timeout,
            @Value("${mediamesh.ml.connect-timeout}") Duration connectTimeout) {
        if (timeout.isNegative() || timeout.isZero()) throw new IllegalArgumentException("ML timeout must be positive");
        this.json=json;this.base=base;this.timeout=timeout;
        http=HttpClient.newBuilder().connectTimeout(connectTimeout).followRedirects(HttpClient.Redirect.NEVER).build();
        breaker=breakers.circuitBreaker("mlSearch");bulkhead=bulkheads.bulkhead("mlSearch");
        timeouts=metrics.counter("mediamesh.ml.search.timeouts");
    }
    public Matches search(Map<String,Object> body) {
        try {
            // Outer bulkhead rejects before the breaker sees a call. No retry layer.
            return bulkhead.executeSupplier(() -> breaker.executeSupplier(() -> request("/internal/search",body)));
        } catch (BulkheadFullException e) {
            throw new SearchFailure("ML_SEARCH_BUSY","bulkhead_full");
        } catch (CallNotPermittedException e) {
            throw new SearchFailure("ML_SEARCH_UNAVAILABLE","circuit_open");
        }
    }
    public Matches similar(Map<String,Object> body) {
        // Same bounded transport; the search-only breaker/bulkhead and SLI do not cover this route.
        return request("/internal/similar",body);
    }
    private Matches request(String path,Map<String,Object> body) {
        CompletableFuture<HttpResponse<String>> pending=null;
        try {
            var request=HttpRequest.newBuilder(base.resolve(path)).timeout(timeout)
                    .header("Content-Type","application/json")
                    .header("X-Request-ID",java.util.Objects.toString(org.slf4j.MDC.get("requestId"),java.util.UUID.randomUUID().toString()))
                    .POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body))).build();
            pending=http.sendAsync(request,HttpResponse.BodyHandlers.ofString());
            // The future completes after the whole body arrives, not merely response headers.
            var response=pending.get(timeout.toNanos(),TimeUnit.NANOSECONDS);
            if (response.statusCode()==400) {
                var error=json.readTree(response.body());
                if (error!=null && "INVALID_INPUT".equals(error.path("error").path("code").asText()))
                    throw new InvalidSearchInput();
            }
            if (response.statusCode()!=200) throw SearchFailure.dependency();
            var matches=json.readValue(response.body(),Matches.class);
            if (matches==null || matches.matches()==null || matches.matches().stream().anyMatch(m ->
                    m==null || m.assetId()==null || !Double.isFinite(m.score())
                    || (m.frameTimestampSeconds()!=null && (!Double.isFinite(m.frameTimestampSeconds()) || m.frameTimestampSeconds()<0))))
                throw SearchFailure.dependency();
            return matches;
        } catch (TimeoutException e) {
            throw timeout(path);
        } catch (ExecutionException e) {
            if (e.getCause() instanceof HttpTimeoutException) throw timeout(path);
            throw SearchFailure.dependency();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw SearchFailure.dependency();
        } catch (JsonProcessingException e) {
            throw SearchFailure.dependency();
        } finally {
            if (pending!=null && !pending.isDone()) pending.cancel(true);
        }
    }
    private SearchFailure timeout(String path) {
        if ("/internal/search".equals(path)) timeouts.increment();
        return new SearchFailure("ML_SEARCH_UNAVAILABLE","timeout");
    }
}
