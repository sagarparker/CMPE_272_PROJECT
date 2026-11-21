# ML integration checkpoint

The [original assignment](../docs/team/03_PERSON_3_ML_RETRIEVAL.md) and
[team contract](../docs/team/00_TEAM_OVERVIEW.md) remain authoritative.

## Preserved interfaces

- `GET /health`: liveness only; does not imply model/database readiness.
- `POST /internal/search`: `{query,limit}` ->
  `{matches:[{assetId,score,frameTimestampSeconds}]}`. Image timestamps are null.
  No S3 URLs, user data, or metadata. Implemented in step 7.
- `POST /internal/similar`: `{assetId,limit}` -> the same matches structure.
  Reserved for step 8.
- Invalid input is 400, absent assets are 404 where applicable. Spring Boot
  owns JWT/RBAC, 401/403, READY/metadata filtering, enrichment, and signed access.
- Error bodies are provisionally `{error:{code,message}}`; confirm the shared
  body format with the backend owner. Never echo submitted secrets in errors.

## Pending agreements (not established by local fixtures)

- Model evaluated locally: CLIP revision
  `327ab6726d33c0e22f920c83f2ff9e4bd38ca37f`, 512 dimensions, L2 normalized,
  `rgb-l2-v1` preprocessing. See MODEL.md for measured quality and limitations.
- Mathew: `assets.id` type, V2xx prerequisites, job fields, claim fencing,
  retries/leases, and atomic vector/job/asset completion behavior. Python
  protocols describe capabilities, not a competing production table schema.
- `/internal/embed-media` appears in the team overview; exact JSON is not
  frozen. Confirm whether an HTTP endpoint is required or shared Python
  functions are the accepted handoff. Do not silently remove the route.
- This plan uses separate API and worker containers sharing Python code;
  confirm this against the overview's single-process recommendation.
- Agree on search defaults/maximum limits, candidate overfetch for backend
  filters, media format/size/duration limits, and error-body format.
- Joel: private service networking, model cache, resource requirements, and
  shared Compose/CI integration. The Compose file here is standalone only.

Steps 1–7 implement local embeddings/indexing, vector persistence, a leased
worker, and HTTP search. The local V300 migration assumes UUID asset IDs until
teammate 2 confirms the FK contract. `ml_dev` job/status fixtures are separate
from production metadata; no V2xx table has been changed. Completion uses the
transaction-aware vector helper to commit vectors/job/local READY atomically.

Readiness now checks a loaded model and the 512-dimensional vector schema/
database. Dependency failures are 503. Invalid inputs are 400, including CLIP
queries over its 77-token budget. Local defaults (limit 20, max 100, query 1,000
characters) and error envelope remain provisional team integration decisions.
Similar media, S3 retrieval, production jobs/statuses, shared deployment/CI,
and the embed-media HTTP handoff remain future work. The browser still calls
Spring Boot only. See LOCAL_WORKFLOW.md for verified commands and boundaries.
