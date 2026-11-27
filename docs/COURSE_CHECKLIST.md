# Evidence for the two course slides

This maps the supplied security and reliability slides to the actual project.
Repository-owned changes are implemented; external account controls are not
claimed without authenticated verification. Current local `origin` points to
`sagarparker/CMPE_272_PROJECT`, while the supplied project URL is
`mathewpius19/Media-Mesh`. No remotes were changed or settings applied to the
other owner's repository.

## Security slide

| Requirement | Implementation / evidence | Status |
|---|---|---|
| Enable repository secret scanning | Trivy source secret scanning in CI; GitHub's native secret scanning and push protection must be enabled/verified in repository Settings | CI implemented; native settings pending owner verification |
| Enable dependency alerts | `.github/dependabot.yml` covers Maven, npm, uv and Actions; Dependabot alerts/dependency graph are separate repository settings | Update configuration implemented; alert setting pending verification |
| Dependency scan fails on known-exploited flaws | `infra/security-check.sh`: source npm/uv plus backend image/JAR/OS inventory; CISA KEV intersection; fail on secrets, KEV hits, missing ecosystem inventories, or scan/feed failure | Implemented and exercised |
| Replace long-lived cloud CI keys with workload identity | Normal CI uses public Azurite fixtures and does not authenticate to cloud. The Azure application uses VM managed identity | No cloud CI keys required; real Azure role assignments still need verification |
| Check ownership on every ID endpoint, with a test | Asset ownership or explicit library/admin object-access policy, tested through HTTP in `ApplicationSecurityTest` | Implemented |
| Require team MFA on GitHub and cloud | Human account/org/identity-provider setting, not application RBAC or a source-code switch | Pending account-owner verification |

The gate initially detected **CVE-2025-24813** in embedded Tomcat 10.1.31.
It failed rather than suppressing the finding. `tomcat.version` is now
10.1.62, preserving the existing Spring Boot architecture. Rescanning the
rebuilt backend found no KEV intersection. Other non-KEV advisories remain in
the report and still need triage; passing this gate does not mean zero CVEs.
The official Trivy 0.76.2 image is pinned by digest. The source scan includes
development dependencies and Markdown secret detection. Matched secret values
are removed from saved reports; output only contains rule/location metadata.
Reports/images are ignored by Git and never uploaded automatically.

The final deployment review also scanned the frontend runtime and detected
**CVE-2026-111497** (brotli-libs) and **CVE-2026-125350** (libxslt) in the old
Nginx/Alpine image. The frontend now uses digest-pinned Nginx 1.30.8/Alpine 3.24;
the combined gate includes both backend and frontend runtime images and passes
with no KEV intersection. Separate scans of the pinned deployment Caddy and
Keycloak images likewise found no KEV intersection at the scan date. Non-KEV
advisories remain; these checks do not certify the complete deployment as free
of vulnerabilities. See the [Azure release runbook](../infra/deploy/README.md).

Run after building the Java artifact:

```bash
mvn -f backend/pom.xml verify
./infra/security-check.sh
```

The source POM is not resolved a second time by Trivy: the backend image is
built and inventoried instead, including resolved nested JARs. This avoids
Maven Central throttling and verifies what is actually packaged. npm, uv and
JAR inventories must all be present; an incomplete scan cannot pass. CISA
catalog downloads use finite timeouts and failures stop the build.

## ID-taking endpoint policy and tests

| Endpoint | Object authorization |
|---|---|
| POST `/api/assets/{id}/complete` | UPLOADER and asset owner |
| PUT `/api/assets/{id}` | UPLOADER and asset owner |
| GET `/api/assets/{id}` | Owner with UPLOADER, or RESEARCHER for a READY library asset |
| POST `/api/assets/{id}/access-url` | RESEARCHER and READY asset |
| POST `/api/assets/{id}/similar` | RESEARCHER and READY asset |
| PUT `/api/admin/users/{id}/roles` | ADMIN, target must exist, and the final admin cannot be removed |

Researchers intentionally read other employees' READY media: sharing the
library is the product's core workflow. Requiring ownership there would break
the agreed policy. Tests instead prove non-owner uploaders cannot read/edit/
complete another uploader's asset, researchers cannot access pending assets,
READY researcher access works, and non-admins cannot promote themselves or
others by changing the ID. Missing IDs and last-admin protection are tested.

## Reliability slide

| Requirement | Evidence |
|---|---|
| `/health` endpoint | Public Spring and Python liveness routes; Python `/ready` separately checks model/database availability |
| Main-route request counter and latency histogram | `mediamesh_search_requests_total` and `mediamesh_search_duration_seconds_bucket` with a 2-second bucket |
| JSON logs and a request ID on every line | Java JSON Logback encoder; Python JSON formatter/context middleware; Nginx JSON access log |
| One journey SLO and error budget | Search: 99% HTTP 200 within 2 seconds over rolling 30 days; Prometheus budget and policy rules |
| Timeouts on outgoing calls | Runtime timeout inventory below, plus bounded CI health/feed requests |
| Present evidence that it works | Demonstration sequence below, unit/rule tests, and real controlled outage/overload tests |

## JSON logging and correlation

Nginx generates a request ID, logs it, and forwards it as `X-Request-ID`.
Spring validates or generates the ID, returns it in the response, places it
in MDC, and forwards it on the ML request. Python uses a ContextVar so sync
search handlers and async middleware see the same ID. Request logs record
method/status/duration, not query text, headers, media references, or JWTs.
Invalid correlation headers are replaced to prevent log injection.

Example shape (illustrative ID):

```json
{"timestamp":"2026-11-25T00:00:00Z","level":"INFO","requestId":"86d1e498-88f4-4a2d-8d0f-61b65da886f7","logger":"com.mediamesh.observability.RequestIdFilter","message":"http_request_complete method=POST status=200 duration_ms=128.0"}
```

Application startup/background lines use `requestId: "system"`; worker job
logs use `job-<uuid>`. They must not pretend to belong to an HTTP request.
Stack traces and newline-containing messages are escaped within one JSON
line. Third-party infrastructure logs (Docker engine, database, Keycloak,
Nginx error diagnostics, JVM startup warnings) retain their own formats; the
JSON contract applies to application logging and Nginx request access logs.

## Outgoing timeout inventory

| Caller / dependency | Bound |
|---|---|
| Spring -> Python | 500ms connect, 1500ms complete-response wait by default |
| Spring -> Blob | 3-second connect, 5-second read/write, 10-second API operation timeout |
| Spring -> JWKS | 1-second connect, 1.5-second socket read |
| Spring -> PostgreSQL | 2-second pool acquisition, 5-second connection, 15-second socket/SQL statement, 5-second lock wait |
| Python -> PostgreSQL | 5-second connect, 15-second statement and TCP user timeout, 5-second lock wait |
| Python -> Blob | 5-second connect, 30-second socket read, bounded retries and maximum bytes |
| Python -> Hugging Face | 10-second metadata and 30-second download socket timeouts |
| Browser -> public API | 10-second AbortSignal timeout |
| Browser -> Blob upload | 120-second XMLHttpRequest timeout |
| Nginx -> upstreams | 3-second connect, 10-second send; finite read timeout |
| Local data/demo utilities | Existing URL reads have finite 15/45-second limits; FFmpeg subprocess deadlines remain enforced |

Socket/statement timeouts are not a universal end-to-end deadline: bounded
retries and slow streaming can increase total operation duration. Browser SSO
navigation, native media playback, and third-party infrastructure have their
own lifecycle/timeouts; they are not rewritten into application fetch calls.
The semantic search SLI still measures total public duration regardless of
which dependency consumed it.

## Account-owner steps still required

1. Sign in as an administrator of the intended GitHub repository. In Settings,
   enable/verify dependency graph, Dependabot alerts/security updates, secret
   scanning, and push protection. A dependabot.yml file alone does not prove
   the alert settings are enabled. Capture screenshots as course evidence.
2. Require and verify MFA for every human GitHub contributor. Organization
   owners can enforce 2FA centrally; a personal repository has no equivalent
   per-repository team enforcement switch. For a personal repo, collect each
   contributor's confirmation or use an organization with the proper policy.
3. Verify MFA for human Azure/Entra users in the student tenant, subject to its
   available policies. Do not place storage keys or client secrets in CI.
4. Assign the VM managed identity the Blob roles documented in the deployment
   runbook. Normal CI has no cloud deployment step or cloud credentials; if a
   deployment job is added later, use Azure federated workload identity.

The shared browser was signed out of GitHub, so protected repository settings
could not be inspected. No MFA, native alert setting, or cloud role assignment is claimed
as configured or verified remotely.

## Final-presentation evidence sequence

1. Show `/health` returning `{"status":"ok"}` and the ML `/ready` response.
2. Run browser acceptance. It prints a non-secret search request ID. Find that
   ID in both `docker compose logs backend` and `docker compose logs ml-api`.
3. Open Prometheus Targets and show the backend UP. Query valid/good/bad counts
   and `mediamesh_search_duration_seconds_bucket{le="2.0"}`.
4. State the SLO: **99% of valid researcher searches return HTTP 200 within two
   seconds, rolling 30 days**. Show observed budget/policy AND history coverage.
   A fresh stack has partial history, not proof of 30 days' achievement.
5. As a labeled worked example: N=10,000 and G=9,950 gives 50 bad requests,
   allowance 100, remaining 50, remaining budget 50%, policy SHIP. This is a
   formula example, not a fabricated production measurement.
6. Run the explicit outage/recovery and 20-request overload demonstrations in
   `docs/observability/RESILIENCE_PATTERNS.md`. Show breaker transitions,
   immediate overload responses, responsive `/api/me`, and real bad counters.
7. Show `MediaMeshSearchHighErrorBudgetBurn` firing after deliberate failures.
   State that Prometheus has no real notification receiver configured.
8. Show test results and the security gate. Explain the detected Tomcat KEV,
   its version fix, and the successful rescan. Separately show the owner-side
   GitHub/MFA settings once they have actually been configured.

References: [GitHub security settings](https://docs.github.com/en/code-security/getting-started/quickstart-for-securing-your-repository),
[organization MFA](https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-two-factor-authentication-for-your-organization/requiring-two-factor-authentication-in-your-organization),
[CISA KEV catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog).

## Current cloud target: Azure student subscription

The primary deployment now uses Azure VM system-assigned managed identity and
user-delegation Blob SAS, with no account keys or client secrets. The legacy AWS
workflow and trust example were removed. CI uses local fixtures and makes no
paid cloud changes.
Azure role assignments, real SAS/CORS and human MFA must be verified in the
actual subscription; automated local tests do not establish those controls.
