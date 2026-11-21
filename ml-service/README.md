# MediaMesh ML service

Steps 1–7 are implemented locally: CLIP embeddings, vector persistence,
image/video indexing, a leased background job worker, and the original internal
semantic-search API. Start with [LOCAL_WORKFLOW.md](LOCAL_WORKFLOW.md) for the
complete Docker queue → worker → HTTP search demonstration, including retry.
See the [original assignment](../docs/team/03_PERSON_3_ML_RETRIEVAL.md) and
[contract notes](CONTRACT_NOTES.md) for integration boundaries.

## Start locally

Requires Docker with Compose/BuildKit named-context support (current Docker
Desktop supports this). No host Python, PostgreSQL, or FFmpeg required. Run
commands from `ml-service/`. Initial builds/downloads need internet access.

```bash
cd ml-service
mkdir -p data/media outputs
cp .env.example .env
docker compose build ml-api ml-tools
docker compose up -d --wait postgres ml-api
curl --fail http://127.0.0.1:8001/health
```

The API binds to localhost port 8001; PostgreSQL has no host port. API docs:
`http://127.0.0.1:8001/docs`. `/health` returns `{"status":"ok"}`. Change
`ML_API_PORT` in `.env` if needed. `/ready` returns 200 only when the model and vector schema/database are available;
otherwise 503. Docker health checks liveness. `/internal/search` is implemented.
Similar/embed-media HTTP routes remain reserved (404). Apply migrations and
cache the model as described in LOCAL_WORKFLOW.md before expecting readiness.

## Download samples and evaluate CLIP (step 2)

```bash
docker compose run --rm ml-tools python -m mediamesh_ml.dataset
docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python -m mediamesh_ml.evaluate --output /outputs/evaluation.json
# Repeat after caching the model, with model network access disabled.
ML_MODEL_OFFLINE=true docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python -m mediamesh_ml.evaluate --output /outputs/evaluation-offline.json
```

The explicit embedding/evaluation commands populate the model cache. API and
worker startup load their models and may download weights unless offline mode is
enabled; health requests themselves never trigger downloads.
Images and text share 512-dimensional normalized vectors. No training required.
[MODEL.md](MODEL.md) records revision, performance, memory, and limitations. The
[dataset documentation](evaluation/README.md), [manifest](evaluation/manifest.json),
and [attribution](evaluation/ATTRIBUTION.md) cover 25 reviewed Commons images,
licenses, checksums, and seven fixed queries. Binaries stay outside Git. Downloads
fail on checksum mismatch. [baseline.json](evaluation/baseline.json) records the
initial real offline run. Evaluation is in-memory, separate from the HTTP API.

## Apply local vector migrations (step 3)

Canonical SQL: [V300](../backend/src/main/resources/db/migration/V300__create_asset_vectors.sql).
Docker copies this through a named build context; no duplicate SQL copy exists.
It requires teammate 2's `assets(id UUID)` prerequisite and does not create/alter
media metadata tables. Confirm the UUID FK before production integration.

For the standalone Compose database only, apply the minimal development asset
fixture and vector migration:

```bash
docker compose run --rm ml-tools python -m mediamesh_ml.migrate --local-fixture
docker compose run --rm ml-tools python -m mediamesh_ml.database
```

Expected: `{"vector_extension": true, "vector_table": true}`. The fixture is
restricted to Compose development/test DBs. The local runner uses checksummed
`ml_schema_migrations` history and a transaction/advisory lock. Reruns are no-ops;
changed applied migrations fail. Missing prerequisites roll back. Startup does
not migrate.

Production integration must use backend Flyway, not the standalone fixture/runner.
Keep standalone data separate from a backend-managed database; do not apply V300
independently through both migration histories. Teammate 2 owns the real asset/job
schema and lifecycle. Local fixtures do not establish those contracts.

`PgVectorRepository` atomically replaces an asset/model vector set, supports
removal, and returns exact cosine matches scoped to model version. Parent-row
locks serialize concurrent replacement/deletion. Its transaction-aware helper
can later participate in atomic worker completion. SQL enforces 512 dimensions,
unit norm, valid timestamps, FK/cascade, and uniqueness including null image
timestamps. HTTP search uses best-frame-per-asset ranking before the result limit. Approximate vector
indexing awaits scale measurements; model and unique/FK indexes exist now.
Connection, statement, and lock timeouts bound database operations.

## Index new images and videos (steps 4–5)

Index once for each new or changed asset. Searching or restarting containers does
not require reindexing; vectors persist in PostgreSQL. There is no directory
watcher. The step 6 worker now automates queued jobs; backend/S3 integration
will enqueue jobs after uploads. See LOCAL_WORKFLOW.md. Keep containers running while using the service.
Rebuild only after code/dependency changes. Model weights stay cached, although
each new inference process loads them into memory.

For the standalone local fixture only, register an asset ID before indexing it.
Production assets will already exist in teammate 2's catalog. The registration
script refuses a production asset schema and never creates upload/status data.

```bash
# Prepare local prerequisites if not already applied.
docker compose run --rm ml-tools python -m mediamesh_ml.migrate --local-fixture

# Existing downloaded photograph: register once, then index.
docker compose run --rm ml-tools python dev/register_asset.py 00000000-0000-4000-8000-000000000401
docker compose run --rm ml-tools python -m mediamesh_ml.index --asset-id 00000000-0000-4000-8000-000000000401 --reference elephant-02.jpg --media-type image

# Download the two credited NPS wildlife clips locally.
docker compose run --rm ml-tools python -m mediamesh_ml.dataset --manifest evaluation/video-manifest.json

docker compose run --rm ml-tools python dev/register_asset.py 00000000-0000-4000-8000-000000000501
docker compose run --rm ml-tools python -m mediamesh_ml.index --asset-id 00000000-0000-4000-8000-000000000501 --reference video-bison.mp4 --media-type video

# Repeating either indexing command replaces its asset/model set, without duplicates.
# Explicitly remove every model version for an asset when needed:
docker compose run --rm ml-tools python -m mediamesh_ml.index --asset-id 00000000-0000-4000-8000-000000000401 --remove

# Offline text-to-video evaluation, separate from the HTTP search API.
ML_MODEL_OFFLINE=true docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python -m mediamesh_ml.evaluate_video --output /outputs/video-evaluation.json
```

Paths are relative to `/data/media` (host `data/media/`); the worker mounts it
read-only while tools can download/create fixtures. The
local adapter rejects path escapes, external symlinks, URLs, nonfiles, empty files,
and files over `ML_MEDIA_MAX_BYTES` (100 MB by default). JPEG/PNG/WebP contents
are validated; animated images are unsupported. Failed decode/inference leaves
the previous vector set intact. Active model versions are replaced atomically;
other versions remain isolated until explicitly removed.

Video containers supported initially: MP4/MOV and WebM/Matroska. FFmpeg is
restricted to file/pipe protocols and those demuxers. ffprobe verifies video
streams, duration (default max 180 seconds), and resolution (default max 4K pixel
count). `ML_VIDEO_MAX_FRAMES` defaults to 8; short clips may yield fewer decoded
frames. Sampling is uniform in time, not scene-change detection. Stored timestamps
come from decoded frame PTS relative to the first frame, not estimated frame
numbers. Frames are scaled to fit 1280x720, encoded in batches, and removed on
success or failure. Probe/extraction share `ML_VIDEO_TIMEOUT_SECONDS` (120 seconds
by default); model inference is outside that decoder timeout. No audio is indexed.
No database writes occur until all frame embeddings are ready.

[Video credits](evaluation/VIDEO_ATTRIBUTION.md) explain the switch to two
public-domain NPS clips after Commons video downloads returned HTTP 429.
[video-baseline.json](evaluation/video-baseline.json) records actual retrieval
results and frame timestamps. Generated clips test mechanics; real NPS footage
tests semantics. The CLI's count/timestamp summary is not a new HTTP contract.

## Verification

```bash
# Fast tests; isolated DB and real-model tests skip unless enabled.
docker compose run --rm ml-tools pytest
docker compose run --rm ml-tools ruff check .
docker compose run --rm ml-tools ruff format --check .
docker compose run --rm ml-tools uv lock --check

# Separate ephemeral PostgreSQL for destructive integration fixtures.
docker compose --profile test up -d --wait postgres-test
docker compose run --rm -e ML_TEST_DATABASE_URL=postgresql://mediamesh:local-test-only@postgres-test:5432/mediamesh_test ml-tools pytest

# Real cached CLIP plus database round-trip; download samples/model first.
docker compose run --rm -e ML_RUN_MODEL_TESTS=1 -e ML_TEST_DATABASE_URL=postgresql://mediamesh:local-test-only@postgres-test:5432/mediamesh_test ml-tools pytest
```

For the opt-in wildlife-video integration check, download the video manifest
above, then add `-e ML_RUN_VIDEO_TESTS=1` to the real-model pytest command.

Destructive fixtures refuse targets other than `postgres-test/mediamesh_test`.
Tests cover empty retrieval, repeat writes, model isolation, timestamps, FK
cascade, transaction rollback, migration checksums, concurrent replacement,
image preparation, local indexing/reindexing, real FFmpeg timestamps, cleanup,
timeouts, corrupt clips, frame limits, and validation. Opt-in real-model tests check dimensions,
normalization, and elephant-vs-lion retrieval through pgvector.

## Worker and integration

Initialize the local queue before starting its daemon:

```bash
docker compose run --rm ml-tools python -m mediamesh_ml.jobs init
docker compose --profile worker up -d ml-worker
```

The worker reuses one model across jobs, claims safely, renews leases, retries
transient failures, and atomically commits vectors and local READY status. Use
[LOCAL_WORKFLOW.md](LOCAL_WORKFLOW.md) for enqueue/status commands and the retry
demo. This is a local adapter in `ml_dev`, not teammate 2's production job schema.
S3 and backend lifecycle integration remain future work, as do similar-media
recommendations. Invalid requests return 400; dependency failures return 503.
The error envelope/default limits await team agreement. Spring Boot owns public
authorization, metadata/status filtering, and result enrichment.

## Configuration, storage, and shutdown

See `.env.example`; Compose uses `.env` for interpolation. Credentials are local
examples only. Change `POSTGRES_*` and `ML_DATABASE_URL` consistently. PostgreSQL
initialization variables affect new volumes only. Settings redact database
credentials in repr/validation errors. Logs use stdout/stderr.

API and worker use the same runtime image; tools add evaluation, fixtures, pytest,
and Ruff. Rebuild after source/dependency changes. The model-cache named volume
is writable by the non-root application user. API and worker mount media
read-only; the tools container mounts it writable for downloads and fixtures.
Generated reports stay in ignored `outputs/`. Separate inference processes each
need model memory. CPU is the local baseline, including macOS Docker.

```bash
docker compose logs --tail 100 ml-api postgres
docker compose --profile worker down
docker compose up -d --wait postgres ml-api
docker compose --profile test stop postgres-test
```

`down` preserves development database/model volumes; `--volumes` would delete
them. The test database uses ephemeral tmpfs. Joel owns shared Compose/CI;
this file is standalone. Deployment requires private networking or agreed
service authentication and external configuration/secrets. Nothing is hosted.
