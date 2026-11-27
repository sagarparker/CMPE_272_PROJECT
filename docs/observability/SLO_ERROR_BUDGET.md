# Semantic search SLO and error budget

## Journey and scope

An authenticated employee with current RESEARCHER access sends a valid
natural-language request to `POST /api/search`. The SLO is **99.0% good
requests over a rolling 30-day window**, allowing a **1.0% error rate**.

A good request returns HTTP 200 in **at most 2 seconds**, including empty
successful results. The timer surrounds the entire synchronous public Spring
request: security/validation, catalog filtering, ML HTTP work, enrichment,
and response serialization. It is not an inference-only timer and does not
include browser rendering, Nginx queueing, or transfer time to the employee.

`SearchSliFilter` starts before Spring Security and records in `finally`.
`SearchSliMetrics` applies this bounded classification:

| Outcome | Counted? | Category |
|---|---|---|
| 200 at or below 2 seconds | Good | none |
| 200 over 2 seconds | Bad | slow |
| ML timeout | Bad | timeout |
| Breaker rejects | Bad | circuit_open |
| Bulkhead rejects | Bad | bulkhead_full |
| ML unavailable/invalid response | Bad | dependency |
| Other 5xx/unhandled exception | Bad | server_error |
| Other unexpected response, including 429 | Bad | unexpected_response |
| 400 invalid input; 401 authentication; 403 role denial | Excluded | none |
| 413 oversized body, 415 unsupported media, 422 invalid input | Excluded | none |

These excluded status codes are reserved for intentional client/auth errors.
Do not convert server problems into 400/401/403 to remove them from the budget.
Only recognized Python `INVALID_INPUT` errors become a public input error;
unexpected ML error responses remain dependency failures. Unhandled exceptions
count as bad even when the container has not yet changed the response status.
The filter skips ERROR redispatch and marks recorded requests to avoid double
counting. Search is synchronous today; converting it to Servlet async requires
moving final recording to an AsyncListener and adding redispatch/timeout tests.

## Metrics

| Prometheus metric | Meaning |
|---|---|
| `mediamesh_search_requests_total` | Completed valid searches, N |
| `mediamesh_search_good_total` | Good searches, G |
| `mediamesh_search_bad_total` | Bad searches; N = G + bad |
| `mediamesh_search_duration_seconds` | Timer: count/sum/max and a 2-second histogram bucket |
| `mediamesh_search_failures_total{category="..."}` | One fixed failure category per bad search |
| `mediamesh_ml_search_timeouts_total` | Actual downstream timeouts |

Counters and all failure categories are registered at startup, including zero
series. Labels never contain query text, identities, JWTs, or asset IDs. The
standard Actuator metrics also expose JVM and process health. The public API
SLI covers only `/api/search`; related-media requests have no search SLI.

## Budget calculations

Prometheus recording rules in `infra/prometheus/search-rules.yml` calculate:

```text
N = sum(increase(valid_requests[30d]))
G = sum(increase(good_requests[30d]))
bad = N - G
SLI = G / N
allowed_bad = N * 0.01
remaining_bad = allowed_bad - bad
remaining_percent = 100 * remaining_bad / allowed_bad
consumed_percent = 100 - remaining_percent
```

No intermediate rounding or clamping is applied. Negative remaining budget
and consumption above 100% are useful evidence of overspending. The allowed
error rate is stored as `0.01` directly, avoiding subtraction artifacts at
policy boundaries. The target is recorded as `0.99`.

| Remaining | Advisory policy | Recorded numeric code |
|---|---|---|
| >= 50% | SHIP | 1 |
| > 0% and < 50% | CAREFUL | 2 |
| <= 0% | FREEZE | 3 |
| No observed valid traffic | INSUFFICIENT_DATA | 0 |

These policies do not block CI or deployments. With N=0, SLI and budget
percentages are absent, not 100%; the policy is 0. On a new or interrupted
monitoring installation, observed budgets/policies are **provisional** until
`mediamesh:search:history_complete` is 1. Do not describe them as a complete
30-day evaluation while that flag is zero.

The history flag conservatively requires 30 days of rule heartbeat samples,
30 days of scrape samples, and no failed backend scrapes. It assumes the
configured 15-second scrape/evaluation intervals and a stable scrape target.
Changing those intervals requires updating the expected 172,800 samples.
A single missed scrape can keep the flag zero until it leaves the window.
This deliberately favors an honest incomplete label over claiming full data.

## View the results

Start the normal stack, then open **http://localhost:9090**. Use Prometheus's
query screen and evaluate these recorded metrics:

| What to view | PromQL |
|---|---|
| Observed SLI percentage | `100 * mediamesh:search:sli_30d` |
| SLO target | `100 * mediamesh:search:slo_target` |
| Remaining / consumed percentage | `mediamesh:search:budget_remaining_percent` / `mediamesh:search:budget_consumed_percent` |
| Advisory policy | `mediamesh:search:budget_policy` |
| Complete-history flag | `mediamesh:search:history_complete` |
| Long / short burn | `mediamesh:search:burn_rate_1h` / `mediamesh:search:burn_rate_5m` |
| Firing high-burn alert | `ALERTS{alertname="MediaMeshSearchHighErrorBudgetBurn",alertstate="firing"}` |
| Scrape status | `up{job="mediamesh-api"}` |

Targets must show `mediamesh-api` UP. The Rules screen shows recording-rule
health; Alerts shows inactive/pending/firing status. An absent ALERTS series
means the alert is not firing, not that the service has a complete history.

## Burn-rate alert

```text
burn_rate = observed_bad_fraction / 0.01
PAGE condition = burn_rate_1h >= 14.4 AND burn_rate_5m >= 14.4
```

Each burn expression requires positive valid traffic in its own window.
Missing metrics and zero traffic cannot fire the burn alert. The rule has no
additional waiting period: both windows must breach at an evaluation.
`severity=page` is a classification only. **No Alertmanager receiver or real
on-call notification is configured.** To deliver notifications later, configure
Prometheus's Alertmanager target and a receiver/routing tree, then test delivery.

The burn alert can operate on recent observations before a full 30 days has
accumulated. Its sample requirements differ from the full-window budget flag.

## Collection, retention, and exposure

Compose adds one Prometheus service with a persistent `prometheus-data`
volume and `--storage.tsdb.retention.time=35d`. No Grafana or dashboard DB is
required. Keep enough disk space for that retention. `docker compose down`
preserves history; deleting volumes deletes it. A fresh volume cannot recreate
past observations and even a full-volume backup can have observation gaps.

Only `/actuator/prometheus` is exposed on a separate management listener.
Host development binds it to 127.0.0.1:9091. In Compose it listens inside the
trusted Docker network and has **no host port mapping**. Nginx does not proxy
it. A narrowly matched management security chain permits scraping; existing
JWT/RBAC behavior for application routes remains unchanged. Prometheus's UI
binds to 127.0.0.1:9090. Do not publish these ports or deploy the UI publicly
without authentication/network controls. Prometheus's admin API is not enabled.

## Initial incident response

1. Check Targets and `up` first. Missing telemetry is a separate condition
   from valid traffic with a high error rate; it must not be treated as healthy.
2. Check failure categories using `sum by(category) (rate(mediamesh_search_failures_total[5m]))`.
3. Inspect `resilience4j_circuitbreaker_state{name="mlSearch"}` and rejected
   calls; inspect bulkhead permits and ML readiness/logs.
4. For timeouts, compare end-to-end latency with ML readiness, inference load,
   PostgreSQL latency, and available CPU. Do not raise timeouts solely to hide
   a reliability problem; a >2-second 200 still consumes the SLO budget.
5. Stop an isolated simulation if one is enabled. Restore the dependency,
   allow recovery probes, and confirm the breaker closes and good traffic resumes.
6. Review the observed budget and history coverage before advising a release.

## Verification and limitations

`infra/check.sh` runs Java classification/resilience tests and `promtool`
configuration/rule tests. Rule fixtures cover both-high, each-one-high,
healthy/no-traffic/missing-series windows, floating-point budget calculations,
and SHIP/CAREFUL/FREEZE boundaries. Java tests verify exact 2-second semantics,
handled/unhandled errors, rejections, exclusions, and exact-once recording.

Prometheus counter increases are sampled estimates with reset handling and
extrapolation, not an audit ledger. Very short process lifetimes or requests
before the first scrape may be missed. Requests that never reach Spring,
process crashes before final recording, and network outages are not captured
as bad searches by this in-process SLI. External journey probes would be needed
for that broader availability claim. No automatic release freeze is implemented.
