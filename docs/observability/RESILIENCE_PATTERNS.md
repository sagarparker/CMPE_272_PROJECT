# ML search resilience and frontend error boundary

## The protected boundary

Semantic search depends on a synchronous Python HTTP call. Without limits,
an ML outage or serialized inference backlog can hold backend request threads
for up to the old 60-second read timeout. We now isolate that dependency with:

```text
Spring public search measurement
  -> existing JWT/RBAC and validation
  -> catalog filtering
  -> semaphore bulkhead
  -> circuit breaker
  -> bounded ML HTTP call
  -> catalog enrichment and response
```

`MlSearchClient.search` uses explicit programmatic Resilience4j decorators:

```java
bulkhead.executeSupplier(() ->
    breaker.executeSupplier(() -> request("/internal/search", body)));
```

The bulkhead is outermost. Its rejections never enter the breaker, but they
still reach the outer public-request SLI. This avoids annotation/aspect-order
ambiguity. No retries, extra application thread pool, Spring Cloud layer,
or wrappers around login/admin/Blob storage operations are introduced. Related-media
calls share the bounded HTTP transport but have no search breaker/bulkhead.

## HTTP timeout

`mediamesh.ml.request-timeout` defaults to 1500ms (`ML_REQUEST_TIMEOUT`).
`connect-timeout` defaults to 500ms (`ML_CONNECT_TIMEOUT`). The Java HTTP
request has a timeout and the response future is awaited with a bounded
wait. `BodyHandlers.ofString` completes after the body is received, so a
server that sends headers and then hangs cannot retain the permit forever.
Pending futures are canceled on exit; interruption restores the thread flag.

The 1.5-second downstream limit leaves part of the 2-second SLO for database,
security, transport overhead, and serialization. It does not guarantee total
public latency below 2 seconds. Measure real warmed and cold-model behavior.

## Circuit breaker

Defaults are configurable in `application.yml` under
`resilience4j.circuitbreaker.instances.mlSearch`:

| Setting | Default |
|---|---|
| slidingWindowType | COUNT_BASED |
| slidingWindowSize | 10 |
| minimumNumberOfCalls | 5 |
| failureRateThreshold | 50% |
| waitDurationInOpenState | 10s |
| permittedNumberOfCallsInHalfOpenState | 2 |

CLOSED admits calls and records outcomes. At least five calls must be
observed before the threshold can open it. OPEN rejects without contacting
Python. After the wait, a new call triggers HALF_OPEN; two successful probes
close it. Failed probes reopen it. There is no background recovery probe.

Dependency failures, timeouts, malformed successful responses, and unexpected
ML statuses are failures. Recognized Python `INVALID_INPUT` responses become
400 and are ignored by breaker statistics. Bulkhead rejections are outside
the breaker. Empty successful results are genuine successes.

## Bulkhead

`resilience4j.bulkhead.instances.mlSearch` defaults to five concurrent calls
and zero wait. A sixth caller immediately receives a structured 503. Permits
are released after success, exception, timeout, or immediate breaker rejection.
A semaphore limits concurrent backend ML calls; it is not a separate backend
thread pool. DB contention, shared CPU, and exhausted servlet threads can still
affect unrelated APIs. It also cannot guarantee that Python stops computing
after the caller times out; client cancellation is not server-side cancellation.

The Python model currently serializes inference with a lock. Five permits are
a teaching default, not a measured optimal capacity. Tune concurrency and
resource allocation from workload measurements, not from the SLO target alone.

## Public failures and metrics

Errors preserve the existing `{error:{code,message}}` envelope:

| Condition | HTTP | Code | SLI failure category |
|---|---|---|---|
| Dependency error/timeout/breaker open | 503 | ML_SEARCH_UNAVAILABLE | dependency/timeout/circuit_open |
| Bulkhead full | 503 | ML_SEARCH_BUSY | bulkhead_full |
| Recognized invalid query | 400 | HTTP_400 | Excluded |

No errors return fake 200/empty results. No internal URLs, queries, tokens,
or exception messages are included in these responses.

Prometheus metrics include:

- `resilience4j_circuitbreaker_state{name="mlSearch",state="closed|open|half_open"}` (active state is 1).
- `resilience4j_circuitbreaker_calls_seconds_count{name="mlSearch",kind="failed|successful|ignored"}`.
- `resilience4j_circuitbreaker_not_permitted_calls_total{name="mlSearch"}`.
- `resilience4j_bulkhead_available_concurrent_calls{name="mlSearch"}` and `resilience4j_bulkhead_max_allowed_concurrent_calls{name="mlSearch"}`.
- `mediamesh_ml_bulkhead_in_use` and `mediamesh_ml_bulkhead_rejected_total`.
- `mediamesh_ml_search_timeouts_total` plus the public search counters/timer.

State transitions shorter than the 15-second scrape interval can be missed
by a gauge; cumulative failure/rejection counters remain useful evidence.
Resilience registries are process-local and reset on restart. Each additional
backend replica has its own five permits and breaker state.

## Local demonstrations

Run the normal acceptance test first so READY synthetic media exists. With
no eligible assets, Spring correctly returns an empty result without calling
ML, which cannot demonstrate a dependency outage.

```bash
./infra/start.sh
cd frontend
npm ci
npx playwright install chromium
npm run test:e2e
```

### Real outage and recovery

From `frontend`, explicitly opt in to the test that stops/restarts the local
ML API. It signs in through the real provider and restores prior roles:

```bash
RUN_CIRCUIT_DEMO=1 npx playwright test reliability-demo --grep 'local outage'
```

It confirms baseline success, stops `ml-api`, sends valid requests until
failures open the breaker, checks fast 503 responses, restarts the API, and
waits for successful recovery. Java tests additionally assert CLOSED, OPEN,
HALF_OPEN, and CLOSED states and verify rejected calls do not reach the stub.

### Delayed overload and unrelated API responsiveness

From the repository root:

```bash
docker compose -f compose.yaml -f compose.reliability-demo.yaml up -d ml-api backend
```

Wait for ML readiness. This explicitly mounts `dev/reliability_demo.py` and
uses a different development-only factory. The normal runtime image contains
neither this file nor these fault controls. It adds no host-facing ML port.

The default simulation delays search by three seconds while the backend
still times out at 1.5 seconds. From `frontend`:

```bash
RUN_RELIABILITY_DEMO=1 npx playwright test reliability-demo --grep 'local delay'
```

The test sends 20 simultaneous valid searches. At least 15 should be rejected
quickly as ML_SEARCH_BUSY; admitted calls time out. `/api/me` is checked during
the burst and must succeed promptly. Inspect the private development counters:

```bash
docker compose exec ml-api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/dev/simulation').read().decode())"
```

For a single burst, peak admitted HTTP calls should be five. Under sustained
traffic, timed-out server work may overlap with newly admitted calls, as noted
above. To observe three-second permit occupancy instead of timeouts, set
`ML_DEMO_REQUEST_TIMEOUT=4s` in this isolated demo; those responses intentionally
violate the public two-second SLO. Set `ML_DEMO_FAILURE=true` for simulated 503s.
Do not deploy this override or mount into a real environment.

Restore normal operation after demonstrating:

```bash
docker compose up -d ml-api backend
```

This removes the mounted factory/delay controls. Check readiness and the
breaker state; it closes after successful probes. Deliberate demo failures
consume the local error budget and may fire the Prometheus alert. They are
not excluded from the SLI. No real paging receiver is configured.

## React error boundary

`ErrorBoundary` wraps the React app. A rendering exception replaces the broken
subtree with a message and Try again/Reload controls, without showing stack
traces or submitted media metadata. Existing asynchronous API error handlers
remain necessary: React rendering boundaries do not catch network rejections
or arbitrary event-handler errors. A browser-only test bundle verifies a
render failure and recovery without adding a production crash switch.

A frontend render failure does not change a completed HTTP 200 into a bad
backend search. This SLO measures the API boundary; a separate browser SLI
would be needed to measure the full visible user experience.

## Files and ownership

Backend: `media/MlSearchClient`, `MlResilienceConfiguration`, `SearchFailure`,
`observability/SearchSliFilter`, and `SearchSliMetrics`. Security integration
is isolated in `ManagementSecurityConfiguration`; application JWT/RBAC is
unchanged. ML simulation is a development entry point without changes to the
normal internal search contract. DevOps owns Prometheus/Compose/CI files;
frontend owns its rendering boundary. These keep the historical workstream
boundaries while Mathew coordinates the integrated project.

## Focused references

- [Resilience4j circuit breaker](https://resilience4j.readme.io/docs/circuitbreaker)
- [Resilience4j semaphore bulkhead](https://resilience4j.readme.io/docs/bulkhead)
- [Micrometer timers](https://docs.micrometer.io/micrometer/reference/concepts/timers.html)
- [React rendering error boundaries](https://react.dev/reference/react/Component#catching-rendering-errors-with-an-error-boundary)
