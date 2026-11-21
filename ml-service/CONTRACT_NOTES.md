# ML integration checkpoint

The [original assignment](../docs/team/03_PERSON_3_ML_RETRIEVAL.md) and
[team contract](../docs/team/00_TEAM_OVERVIEW.md) remain authoritative.

## Preserved interfaces

- `GET /health`: liveness only; does not imply model/database readiness.
- `POST /internal/search`: `{query,limit}` ->
  `{matches:[{assetId,score,frameTimestampSeconds}]}`. Image timestamps are null.
  No S3 URLs, user data, or metadata. Implement in step 7.
- `POST /internal/similar`: `{assetId,limit}` -> the same matches structure.
  Reserved for step 8.
- Invalid input is 400, absent assets are 404 where applicable. Spring Boot
  owns JWT/RBAC, 401/403, READY/metadata filtering, enrichment, and signed access.
- Error bodies are provisionally `{error:{code,message}}`; confirm the shared
  body format with the backend owner. Never echo submitted secrets in errors.

## Pending agreements (not established by local fixtures)

- Model revision, dimensions, and normalization: evaluate and pin in step 2,
  before writing the vector migration.
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

Step 1 does not implement search, embeddings, production job processing, or
S3. Unavailable features must not return mock successful responses. Readiness
will remain 503 until real dependencies are wired and checked in later steps.
