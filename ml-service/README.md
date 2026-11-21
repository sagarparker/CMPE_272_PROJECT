# MediaMesh ML service

A local, Docker-based service for turning wildlife photographs and sampled video
frames into searchable CLIP embeddings. It provides background indexing,
PostgreSQL/pgvector persistence, and an internal FastAPI semantic-search API.

**Implemented:** steps 1–7, including image/video indexing, a leased worker,
retry handling, best-frame ranking, and the original search response contract.
**Future:** similar-media recommendations, production Spring Boot job/status and
private-S3 integration, shared CI/orchestration, and deployment acceptance.

The current application runs locally. ML-only mode starts **PostgreSQL, the ML
API, and the worker**. The dummy frontend is optional. The current queue adapter
still uses guarded local fixtures; ML-only mode is not a production deployment.

## Contents

- [Quick start with the script](#quick-start-with-the-script)
- [Architecture](#architecture)
- [Components and what is only for testing](#components-and-what-is-only-for-testing)
- [End-to-end indexing flow](#end-to-end-indexing-flow)
- [End-to-end search flow](#end-to-end-search-flow)
- [Individual Docker controls](#individual-docker-controls)
- [Samples, uploads, and indexing commands](#samples-uploads-and-indexing-commands)
- [API contract](#api-contract)
- [Configuration and storage](#configuration-and-storage)
- [Testing and evaluation](#testing-and-evaluation)
- [Future integrated architecture](#future-integrated-architecture)
- [Troubleshooting](#troubleshooting)
- [Code map and related documents](#code-map-and-related-documents)

## Quick start with the script

### Requirements

- A running Docker engine, such as Docker Desktop, and Docker Compose with
  BuildKit/named build-context support.
- Bash to execute the management script.
- Internet access for the first image/dependency/model downloads. After the model
  is cached, inference can run offline.

Host Python, PostgreSQL, FFmpeg, Node.js, and frontend build tools are not required.
CPU is the tested baseline, including Docker on macOS. The API and worker each
load a model instance; budget memory for both. See [MODEL.md](MODEL.md) for the
measured model requirements and retrieval limitations.

### Start ML services only — default

Run from the **repository root**:

```bash
./ml-service/manage.sh start
```

This starts `postgres`, `ml-api`, and `ml-worker`. It stops the dummy frontend if
it was already running. It does not start the test database, run tests, download
sample datasets, seed demo assets, or reindex existing media. It builds only the
runtime image; it does not build the optional frontend/tools image.

Startup performs these steps:

1. Reuse cached Docker build layers or build the runtime image if source changed.
2. Start PostgreSQL and wait for database health.
3. Idempotently apply the vector migration and required standalone local fixtures.
4. Load/cache the pinned CLIP model using a temporary runtime container.
5. Start API and worker containers and verify API readiness.
6. Print the actual API URL, including a configured custom port.

The bootstrap containers exit after their commands. They use the runtime image
with a read-only mount of the local SQL fixtures, not a persistent testing service.
The worker needs that local job adapter until the production backend contract is
integrated. It does not use the dummy frontend to perform indexing.

### Opt in to the test frontend

```bash
./ml-service/manage.sh start --with-ui
```

This also builds the tools image and starts `ml-dev-ui`. Open
**http://127.0.0.1:8002** to upload files, index samples, inspect jobs, search,
preview media, reindex, remove embeddings, or run the retry demonstration.
It uses the real worker and search API rather than mock inference/results.

### Stop, restart, status, and logs

```bash
./ml-service/manage.sh stop
./ml-service/manage.sh restart
./ml-service/manage.sh restart --with-ui
./ml-service/manage.sh status
./ml-service/manage.sh logs
./ml-service/manage.sh logs ml-worker
./ml-service/manage.sh logs ml-dev-ui
./ml-service/manage.sh help
```

`stop` stops frontend/API/worker, allowing the worker to drain, then stops
PostgreSQL. It retains containers, database contents, embeddings, cached weights,
and uploaded files. `restart` defaults to ML-only mode; add `--with-ui` to include
the frontend. `logs` follows core-service output until Ctrl+C; exiting logs does
not stop services. `status` also shows optional containers that are stopped.

The script works from any directory when invoked by its absolute path. It uses
`ml-service/.env` when present and does not overwrite it. Defaults work without
that file. To customize settings on first setup, copy `.env.example` to `.env`
inside `ml-service/` before starting; preserve any existing `.env`.

### Control one service through the script

These commands run from the repository root. Named starts prepare the required
runtime dependencies; they do not select the full-stack mode or stop unrelated
services. Starting the UI alone can also start its API/database dependencies,
but it does not start the worker. Use `start --with-ui` for the complete test flow.

| Service | Start with script | Stop with script |
|---|---|---|
| PostgreSQL | `./ml-service/manage.sh start postgres` | `./ml-service/manage.sh stop postgres` |
| API | `./ml-service/manage.sh start ml-api` | `./ml-service/manage.sh stop ml-api` |
| Worker | `./ml-service/manage.sh start ml-worker` | `./ml-service/manage.sh stop ml-worker` |
| Optional frontend | `./ml-service/manage.sh start ml-dev-ui` | `./ml-service/manage.sh stop ml-dev-ui` |

Use `restart SERVICE` for a named restart, for example
`./ml-service/manage.sh restart ml-worker`. Stop application services before the
database when shutting down manually; plain `stop` enforces that order for you.

The isolated `postgres-test` service is managed separately, not by this script.

### Default addresses

| Service | Host address | Container address |
|---|---|---|
| ML API | http://127.0.0.1:8001 | `http://ml-api:8000` |
| API documentation | http://127.0.0.1:8001/docs | `/docs` on `ml-api` |
| Liveness | http://127.0.0.1:8001/health | `/health` on `ml-api` |
| Readiness | http://127.0.0.1:8001/ready | `/ready` on `ml-api` |
| Optional dummy frontend | http://127.0.0.1:8002 | `http://ml-dev-ui:8080` |
| PostgreSQL | No published host port | `postgres:5432` |
| Worker | No HTTP listener or published port | Polls the database |

`/health` is process liveness. `/ready` checks a loaded model and the compatible
vector schema/database. Readiness is not a worker health check. Docker's API
health check uses liveness; the script separately verifies readiness.

## Architecture

### Current local architecture

This diagram includes the core ML path and optional development/testing paths.
Only API, worker, and database start by default. The dummy UI and tools are
explicitly labeled; they do not create a production browser API.

```mermaid
flowchart TB
    Client["Internal client / curl"]
    Browser["Browser — optional local test page"]

    subgraph Docker["Local Docker Compose network"]
        API["ml-api<br/>FastAPI + Uvicorn<br/>CLIP text encoder"]
        Worker["ml-worker<br/>Job loop + CLIP image encoder<br/>Pillow + FFmpeg / ffprobe"]
        DB[("postgres<br/>asset_vectors + local asset/job fixtures")]
        UI["ml-dev-ui — TEST ONLY<br/>HTML / JS + local gateway"]
        Tools["ml-tools — ON DEMAND<br/>Setup, CLI, evaluation, pytest, Ruff"]
        TestDB[("postgres-test — TEST ONLY<br/>Isolated ephemeral database")]
    end

    Media[("Host data/media/<br/>Samples and uploads")]
    Cache[("Persistent model-cache volume")]
    Data[("Persistent postgres-data volume")]

    Client -->|"POST /internal/search"| API
    Browser --> UI
    UI -->|"Proxy original search request"| API
    UI -->|"Register fixture asset and enqueue"| DB
    UI -->|"Write upload / serve preview"| Media
    Worker -->|"Claim, renew, retry, commit"| DB
    Media -->|"Read-only media access"| Worker
    API -->|"Exact cosine retrieval"| DB
    Cache --> API
    Cache --> Worker
    DB --- Data
    Tools -.-> DB
    Tools -.-> TestDB
    Tools -.-> Media
    Tools -.-> Cache
```

The API and worker share Python source and a Docker runtime image, but run as
separate processes. Each loads its own model into RAM. The UI gateway loads no
model; it forwards searches and creates local jobs. Media mounts are read-only
for API/worker and writable for the tools/UI where uploads/downloads are needed.

## Components and what is only for testing

### Services and containers

| Component | Responsibility | Role / maturity |
|---|---|---|
| `ml-api` | Validates internal search, encodes text, returns ranked asset IDs/scores/timestamps | Reusable application component |
| `ml-worker` | Prepares image/video embeddings, renews claims, commits results, handles retries | Reusable worker logic; current job/media adapters are local |
| `postgres` + pgvector | Persists vectors and performs similarity queries | Required application storage; this Compose instance is for local development |
| `ml-dev-ui` | Dummy upload/search/job console and `/dev/*` gateway | **Testing only**, opt-in `ui` profile; separate from production React |
| `ml-tools` | Runs setup, indexing CLIs, model caching, evaluation, tests, and lint | **Development/test utility**, temporary `run --rm` containers |
| `postgres-test` | Separate target for destructive integration fixtures | **Testing only**, opt-in `test` profile; data uses ephemeral tmpfs |

The normal ML-only start does not launch `ml-dev-ui`, `ml-tools`, or
`postgres-test`. The management script uses short-lived runtime containers for
bootstrap and model caching. The `tools` build target adds development files and
dependencies to the shared runtime layers; core runtime excludes pytest/Ruff.

### Libraries and processing components

| Component | Use |
|---|---|
| Python 3.11 | Application and worker language |
| FastAPI / Pydantic / Uvicorn | Internal HTTP API, strict validation, OpenAPI, and serving |
| Sentence Transformers | Loads the compatible image/text embedding model |
| PyTorch CPU | Executes neural-network inference |
| CLIP `clip-ViT-B-32` | Maps text and images to the same 512-dimensional space |
| Pillow | Decodes images, checks formats/size, applies EXIF orientation and RGB conversion |
| ffprobe | Inspects video streams, dimensions, and duration |
| FFmpeg | Extracts bounded, timestamped frames; no audio transcription |
| Psycopg 3 | Database connections, transactions, claim locking, and vector queries |
| pgvector | Stores `vector(512)` and computes cosine distance |
| uv + `uv.lock` | Reproducible application dependencies |
| pytest / Ruff | Development verification and formatting/lint checks |

The pinned model revision is
`327ab6726d33c0e22f920c83f2ff9e4bd38ca37f`. Image/text vectors are L2-normalized.
The stored model fingerprint includes model name, revision, and `rgb-l2-v1`
preprocessing. Different fingerprints are searched separately. We use pretrained
inference; adding media does not train or fine-tune the model.

### Database objects, files, and fixtures

| Item | Purpose | Testing-only status |
|---|---|---|
| `asset_vectors` | Asset UUID, model version, embedding, optional frame timestamp | Application schema, owned by teammate 3 |
| `assets(id UUID)` from `dev/bootstrap_assets.sql` | Minimal FK prerequisite while the backend catalog is unavailable | **Local fixture only**, not the production catalog |
| `ml_dev.index_jobs` | Standalone queue with attempts, availability, claim token, lease, and error code | **Local adapter/fixture only**, not teammate 2's job schema |
| `ml_dev.asset_states` | Demonstrates local `PROCESSING`, `READY`, and `FAILED` states | **Local fixture only**, not production metadata |
| `ml_schema_migrations` / local migration CLI | Checksummed standalone vector-migration history | **Local development workflow**; production uses backend Flyway |
| Evaluation manifests, queries, and baselines | Repeatable retrieval demonstration and attribution | **Evaluation only**, not training data or a runtime requirement |
| `dev/demo.py` / `dev/register_asset.py` | Demonstrates queue-to-search and registers local fixture UUIDs | **Local testing only** |
| Generated test-pattern clips / test fake encoders | Verify decoding, timestamps, and failure mechanics cheaply | **Tests only**; real CLIP/NPS checks are separately enabled |
| `data/media/` and `outputs/` | Local media and generated reports/screenshots | Ignored local data, not committed deployment assets |

The vector migration is
[V300__create_asset_vectors.sql](../backend/src/main/resources/db/migration/V300__create_asset_vectors.sql).
It requires `assets.id` to be UUID, enables pgvector, and enforces dimensions,
unit norm, valid timestamps, FK/cascade, and uniqueness including null image
timestamps. Model-version and uniqueness indexes support the current small exact
search. Approximate vector indexes are deferred until scale measurements justify them.

Production integration must confirm the asset-ID and job/status contracts with
teammate 2. The local fixture runner is guarded against production-style assets.
Do not mix its migration history with backend Flyway on the same database.

## End-to-end indexing flow

The same preparation code supports the worker and direct indexing CLI. The worker
performs expensive preparation outside a database transaction and commits only
while it still owns the job.

```mermaid
sequenceDiagram
    actor User
    participant UI as Optional test UI / gateway
    participant Media as Local media directory
    participant DB as PostgreSQL + pgvector
    participant Worker as Background worker
    participant Prep as Pillow / FFmpeg
    participant Model as CLIP image encoder

    User->>UI: Upload image/video, or select sample
    UI->>Media: Finish writing uploaded file
    UI->>DB: Register fixture asset and enqueue job
    DB-->>UI: Job ID / PENDING
    UI-->>User: Accepted, show job progress
    Worker->>DB: Claim job, increment attempt, assign lease token
    Note over Worker,DB: Heartbeat renews ownership while preparation runs
    Worker->>Media: Read referenced media
    alt Processing succeeds
        alt Image
            Worker->>Prep: Decode, validate, orient, convert to RGB
        else Video
            Worker->>Prep: Probe limits and sample frames
            Prep-->>Worker: Frame images and decoded timestamps
        end
        Worker->>Model: Encode image/frame batch
        Model-->>Worker: Normalized 512-dimensional vectors
        Worker->>DB: Verify claim and atomically replace vector set
        Worker->>DB: In same transaction, set job SUCCEEDED and local asset READY
    else Decode, inference, or commit fails
        Worker->>DB: Record error code, retry with delay or mark FAILED
    end
    UI->>DB: Poll through gateway every two seconds
    DB-->>UI: Updated state, attempts, vector count
    UI-->>User: Show READY, retry progress, or failure

```

Without the frontend, a backend producer or local CLI creates the job. Merely
copying a file into `data/media/` does not create a job; there is no directory
watcher. The test UI's upload action does enqueue automatically.

### Job lifecycle and consistency

```mermaid
stateDiagram-v2
    [*] --> PENDING: Enqueue
    PENDING --> PROCESSING: Claim and increment attempt
    PROCESSING --> PROCESSING: Renew lease
    PROCESSING --> SUCCEEDED: Atomic vectors and READY commit
    PROCESSING --> PENDING: Retryable failure or expired lease with attempts left
    PROCESSING --> FAILED: Permanent rejection or exhausted attempts
    SUCCEEDED --> [*]
    FAILED --> [*]
```

- One active job per asset; identical active enqueue requests deduplicate.
- `FOR UPDATE SKIP LOCKED` prevents competing workers from claiming the same
  available job. Each claim receives a new token.
- Default lease: 60 seconds. Heartbeat interval: the smaller of 10 seconds and
  one-third of the lease. Expired claims are recovered on worker polling.
- Default maximum attempts: 3. Retry delays use exponential backoff starting at
  2 seconds, capped at 60 seconds.
- Completion verifies ownership, replaces vectors, and updates local success/
  READY status in one transaction. A failed status write rolls back vectors too.
- Stale owners cannot complete or fail a reassigned claim. Computation can repeat
  after lease loss; committed indexing remains idempotent.
- Explicit validation failures/unrecognized images are terminal. Retryable I/O,
  inference, and decoder-timeout failures follow bounded attempts.
- SIGTERM stops new claims and drains current work. The worker has a 150-second
  Docker stop grace period. Forced stops recover through lease expiry.

Indexing the same asset/model replaces its vector set, including obsolete video
frames. Failed replacement preserves the old set. Removing an index deletes its
vectors, not its original file. Searching or restarting services does not reindex
media. Each search only generates a new text-query embedding.

## End-to-end search flow

```mermaid
sequenceDiagram
    actor Client as Browser / internal client
    participant UI as Optional test gateway
    participant API as ML API
    participant Model as CLIP text encoder
    participant DB as PostgreSQL + pgvector

    Client->>UI: POST /dev/search with query and limit
    UI->>API: Forward POST /internal/search unchanged
    Note over Client,API: curl or future Spring Boot can call the internal API directly
    API->>API: Validate input and check dependencies
    API->>Model: Encode query in the same embedding space
    Model-->>API: Normalized text vector
    API->>DB: Filter model version and compute cosine similarity
    DB-->>API: Best frame per asset, ranked before limit
    API-->>UI: matches: asset IDs, scores, optional timestamps
    UI-->>Client: Same search JSON
    Client->>UI: Request local media preview by asset ID
    UI-->>Client: Image or video byte-range response
    Note over Client: Test page joins local metadata and seeks video to the matching timestamp
```

The ML API returns candidates only. In the future integrated application,
Spring Boot checks authorization, READY status, and metadata filters, enriches
results, and issues authorized media-access URLs. The dummy UI's local preview
routes are a testing substitute for that flow.

## Individual Docker controls

All commands in this section run from **`ml-service/`**:

```bash
cd ml-service
```

### Initial Docker setup, without the script

```bash
mkdir -p data/media outputs
# Optional, first setup only; preserve any existing .env:
# cp .env.example .env

docker compose build ml-api
docker compose up -d --wait postgres

# Bootstrap only the guarded standalone local schema, using the runtime image.
docker compose run --rm --no-deps -v "$PWD/dev:/app/dev:ro" ml-api python -m mediamesh_ml.migrate --local-fixture
docker compose run --rm --no-deps -v "$PWD/dev:/app/dev:ro" ml-api python -m mediamesh_ml.jobs init

# Populate/validate the pinned model cache before starting long-running processes.
docker compose run --rm --no-deps ml-api python -m mediamesh_ml.embeddings
```

### Start and stop each service

Run the relevant command separately. `up` may start declared dependencies; `stop`
does not stop other services automatically. Stop the worker/API/UI before
stopping their database. Worker shutdown can wait for its current job to drain.

| Service | Start | Stop |
|---|---|---|
| Database | `docker compose up -d --wait postgres` | `docker compose stop postgres` |
| ML API | `docker compose up -d --wait ml-api` | `docker compose stop ml-api` |
| Worker | `docker compose --profile worker up -d ml-worker` | `docker compose --profile worker stop ml-worker` |
| Optional test frontend | `docker compose --profile ui up -d --wait ml-dev-ui` | `docker compose --profile ui stop ml-dev-ui` |
| Isolated test database | `docker compose --profile test up -d --wait postgres-test` | `docker compose --profile test stop postgres-test` |

Before starting the optional UI, build its shared tools image:

```bash
docker compose build ml-tools
```

`ml-tools` is an on-demand service rather than a daemon:

```bash
docker compose run --rm ml-tools python -m mediamesh_ml.database
```

That temporary container exits and is removed automatically. It does not need a
separate stop command. The optional UI uses the tools image but starts Uvicorn
instead of pytest; it does not run the test suite in the background.

### Start/stop groups directly

```bash
# Core ML only, after the initial setup above:
docker compose --profile worker up -d --wait ml-api ml-worker

# Core plus optional frontend, after building ml-tools:
docker compose --profile worker --profile ui up -d --wait ml-api ml-worker ml-dev-ui

# Drain applications before stopping PostgreSQL:
docker compose --profile worker --profile ui stop ml-dev-ui ml-worker ml-api
docker compose stop postgres
```

Direct Docker commands do not implement mode switching: they leave other already
running services alone. Stop `ml-dev-ui` explicitly when switching to core-only
with raw Docker. The management script handles that switch for you.

### Inspect or restart an individual service

```bash
docker compose --profile worker --profile ui ps -a
docker compose logs --tail 100 -f ml-api
docker compose --profile worker logs --tail 100 -f ml-worker
docker compose --profile ui logs --tail 100 -f ml-dev-ui
docker compose logs --tail 100 -f postgres

# Restart existing containers; this does not rebuild source changes.
docker compose restart ml-api
docker compose --profile worker restart ml-worker
docker compose --profile ui restart ml-dev-ui

# Inspect database interactively with default local credentials.
docker compose exec postgres psql -U mediamesh -d mediamesh
```

After source changes, rebuild `ml-api` and, if using development tools/UI,
`ml-tools`, then use `up -d` to recreate affected containers. `manage.sh start`
does the core build automatically; `start --with-ui` builds both targets.

`stop` keeps containers and volumes. `down` removes containers/networks while
retaining named volumes by default. Adding `--volumes` deletes stored database
and model-cache volumes; it is not part of the management script. Bind-mounted
uploads remain in host `data/media/`.

## Samples, uploads, and indexing commands

### Download and use the evaluation samples

From `ml-service/`, after building the tools image:

```bash
mkdir -p data/media outputs
docker compose run --rm ml-tools python -m mediamesh_ml.dataset
docker compose run --rm ml-tools python -m mediamesh_ml.dataset --manifest evaluation/video-manifest.json
```

The collection contains **25 wildlife images** from Wikimedia Commons and **2
wildlife clips** from the US National Park Service. Each file has a pinned URL,
checksum, source, and usage/attribution record. Media binaries are ignored by Git
and are not present in a fresh clone. The management script does not download
or index them automatically. Reload the browser after downloading samples, then
choose **Index selected sample** or **Index all samples**.

See [image attribution](evaluation/ATTRIBUTION.md),
[video attribution](evaluation/VIDEO_ATTRIBUTION.md), and the
[evaluation guide](evaluation/README.md). These samples evaluate pretrained CLIP;
they are not used for training. Generated test clips check mechanics separately
from real wildlife retrieval.

### Use your own media

With the optional frontend running, choose **Upload & index**. The gateway writes
the file under `data/media/`, registers a local fixture UUID, and queues the job.
The worker performs inference automatically. Search after its status is READY.

Without the frontend, place the file in `data/media/`, register its UUID in the
local fixture, and enqueue it. The example below uses a downloaded photo:

```bash
docker compose build ml-tools
docker compose run --rm ml-tools python dev/register_asset.py 00000000-0000-4000-8000-000000000701
docker compose run --rm ml-tools python -m mediamesh_ml.jobs enqueue --asset-id 00000000-0000-4000-8000-000000000701 --reference elephant-02.jpg --media-type image
```

Use `--media-type video` and a video reference for a clip. The enqueue command
returns a job UUID. Replace `JOB_UUID` below with that value:

```bash
docker compose run --rm ml-tools python -m mediamesh_ml.jobs status JOB_UUID
```

Reenqueueing after a terminal job explicitly requests reindexing. Identical
active requests deduplicate. The backend's future upload-completion idempotency
must be agreed separately; these local fixture rules are not its public API.

### Direct indexing, bypassing the queue

These commands are useful for testing components in isolation. The asset must
already exist. Direct indexing persists vectors but does not perform the worker's
job/status lifecycle.

```bash
docker compose run --rm ml-tools python -m mediamesh_ml.index --asset-id 00000000-0000-4000-8000-000000000701 --reference elephant-02.jpg --media-type image
# For a registered video asset, use --media-type video and its file reference.

# Explicit removal of all model versions for this asset; original file is kept:
docker compose run --rm ml-tools python -m mediamesh_ml.index --asset-id 00000000-0000-4000-8000-000000000701 --remove
```

### Input limits and video sampling

- Images: JPEG, PNG, and WebP; animated images are rejected. Decoding applies
  EXIF orientation, RGB conversion, and a 20-million-pixel limit.
- Media reference: local file inside `ML_MEDIA_ROOT`. External URLs, path escapes,
  outside-root symlinks, directories, empty files, and oversized files are rejected.
- Default file limit: 100,000,000 bytes, including streamed UI uploads.
- Videos: MP4/MOV and WebM/Matroska, with a video stream; default maximum duration
  180 seconds and resolution product 8,294,400 pixels.
- Default maximum sampled frames: 8. Short clips can yield fewer frames. Sampling
  is uniform in time, not scene detection or full temporal video understanding.
- Frames fit within 1280x720. Stored times come from decoded PTS relative to the
  first video frame; matching offsets are approximate moments.
- Probe/extraction share a default 120-second timeout. Model inference is outside
  that decoder timeout. Temporary frames are removed on success/failure.
- Audio is not indexed or transcribed. Browser preview codec support can differ
  from FFmpeg decoding support.

## API contract

The [original assignment](../docs/team/03_PERSON_3_ML_RETRIEVAL.md) remains
canonical. The original internal search route, field names, nesting, and timestamp
semantics are preserved. Changing Flask to FastAPI did not change the contract.

### `POST /internal/search`

```json
{
  "query": "elephants drinking at a watering hole at sunset",
  "limit": 20
}
```

Illustrative response; IDs, scores, order, and offsets depend on indexed data:

```json
{
  "matches": [
    {
      "assetId": "00000000-0000-4000-8000-000000000401",
      "score": 0.35,
      "frameTimestampSeconds": null
    },
    {
      "assetId": "00000000-0000-4000-8000-000000000501",
      "score": 0.21,
      "frameTimestampSeconds": 18.385
    }
  ]
}
```

```bash
curl --fail http://127.0.0.1:8001/internal/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"a herd of bison grazing in a green valley","limit":10}'
```

- Return one candidate per asset with its best-scoring frame, then apply `limit`.
  Ties are deterministic. Images use `null`; videos use numeric seconds.
- Scores are cosine similarities, can be negative, and are not probabilities.
- No embeddings, metadata, user information, or S3 URLs are returned.
- Empty index: `200` with `{"matches":[]}`.
- Invalid input: `400`, including empty/non-string queries, invalid limits,
  unknown fields, malformed JSON, and text exceeding the CLIP token budget.
- Dependency/model/schema failure: `503`, not a successful empty result.
- Current local defaults: limit 20, maximum 100, trimmed query up to 1,000
  characters. CLIP allows 77 tokens including special tokens; no silent truncation.
  Default limits and error-body format remain team integration decisions.

Example error envelope:

```json
{"error":{"code":"INVALID_INPUT","message":"Invalid request input"}}
```

OpenAPI documents validation as 400 rather than FastAPI's default 422.
Spring Boot will own JWT/RBAC, public 401/403 behavior, metadata/READY filtering,
and media authorization. The local ML API does not authenticate individual users.

### Other routes

| Route | Status and purpose |
|---|---|
| `GET /health` | Implemented liveness; `200 {"status":"ok"}` |
| `GET /ready` | Implemented model/schema/database readiness; 200 or 503 |
| `POST /internal/similar` | Reserved for step 8; currently 404 |
| `POST /internal/embed-media` | Listed in team overview; HTTP handoff/schema still pending; currently 404. Worker embeds through shared Python functions. |
| `/dev/*` on port 8002 | Test gateway only: uploads, local fixtures/jobs/previews, and search proxy; not part of the ML API contract |

## Configuration and storage

See [.env.example](.env.example) and [config.py](src/mediamesh_ml/config.py).
Compose reads `.env` for interpolation; shell environment values can override it.
The script does not source/evaluate the file as shell code or overwrite it.

| Setting | Default / purpose |
|---|---|
| `ML_API_PORT` / `ML_DEV_UI_PORT` | Host ports 8001 / 8002 |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local example credentials/database; keep consistent with `ML_DATABASE_URL` |
| `ML_DATABASE_URL` | Container-to-container PostgreSQL DSN, using host `postgres` |
| `ML_MODEL_NAME` / `ML_MODEL_REVISION` | Pinned CLIP model and immutable revision |
| `ML_MODEL_OFFLINE` | `false`; set true after caching to prevent model downloads |
| `ML_DEVICE` / `ML_EMBEDDING_BATCH_SIZE` | CPU / 8 |
| `ML_WORKER_POLL_SECONDS` | 2 seconds |
| `ML_JOB_LEASE_SECONDS` / `ML_JOB_MAX_ATTEMPTS` | 60 seconds / 3 attempts |
| `ML_JOB_RETRY_BASE_SECONDS` / `ML_JOB_RETRY_MAX_SECONDS` | 2 / 60 seconds |
| `ML_MEDIA_MAX_BYTES` | 100,000,000 bytes |
| `ML_VIDEO_MAX_FRAMES` / `ML_VIDEO_MAX_DURATION_SECONDS` | 8 / 180 seconds |
| `ML_VIDEO_MAX_PIXELS` / `ML_VIDEO_TIMEOUT_SECONDS` | 8,294,400 pixels / 120 seconds |
| `ML_DB_CONNECT_TIMEOUT_SECONDS` / `ML_DB_STATEMENT_TIMEOUT_MS` | 5 seconds / 15,000 milliseconds |
| `ML_LOG_LEVEL` | INFO; logs go to container stdout/stderr |

Container paths are `/data/media`, `/data/models`, and `/tmp` for extracted
frames. Compose fixes the media/cache mounts to these paths. Model/schema
dimensions are 512; changing dimensions requires a deliberate model/migration/
reindexing change, not merely an environment-variable edit.

| Storage | Persists when stopped? | Contents |
|---|---|---|
| `postgres-data` named volume | Yes | Assets/fixtures, jobs, vectors, migration history |
| `model-cache` named volume | Yes | Downloaded model snapshot and tokenizer/processor files |
| Host `data/media/` | Yes | Downloaded samples, uploaded files, retry-demo input copies |
| Container temporary extraction directory | No durable state intended | Frame JPEGs, cleaned by the sampler |
| Host `outputs/` | Yes | Optional evaluation/browser/demo reports and screenshots |
| `postgres-test` tmpfs | Ephemeral | Integration-test data only |

`.env`, downloaded media/model caches, generated outputs, and Python caches stay
outside Git. PostgreSQL initialization variables affect new volumes only;
changing the environment password does not change an already-initialized DB.
API and worker have independent in-memory models; the cached weights are shared
on disk. Source changes reuse dependency layers in Docker builds.

## Testing and evaluation

From `ml-service/`, build the tools image first. Fast tests skip isolated-DB and
real-model checks unless explicitly enabled:

```bash
docker compose build ml-tools
docker compose run --rm ml-tools pytest
docker compose run --rm ml-tools ruff check .
docker compose run --rm ml-tools ruff format --check .
docker compose run --rm ml-tools uv lock --check
```

For the complete suite, cache the model and download both sample manifests first:

```bash
docker compose --profile test up -d --wait postgres-test
docker compose run --rm -e ML_RUN_MODEL_TESTS=1 -e ML_RUN_VIDEO_TESTS=1 -e ML_TEST_DATABASE_URL=postgresql://mediamesh:local-test-only@postgres-test:5432/mediamesh_test ml-tools pytest
docker compose --profile test stop postgres-test
```

Destructive fixtures refuse the development database and target only
`postgres-test/mediamesh_test`. The current implementation has been validated
with 93 Python tests plus real-browser checks for uploads, search, video seeking,
retry, removal, reindexing, selected samples, all 27 sample jobs, and mobile layout.
The full test suite uses actual CLIP for opt-in semantic checks and controlled
fixtures for mechanics; mocked encoders alone are not retrieval-quality evidence.

Reproduce the local queue-to-worker-to-HTTP demonstration, including retry:

```bash
mkdir -p outputs
docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python dev/demo.py --retry-demo --output /outputs/end-to-end.json
```

It requires the API/worker/database and sample files, but not the dummy frontend.
The retry demonstration needs at least two attempts and a delay of at least one
second. It retains its small local input copy so the resulting READY fixture
still has a valid media reference.

Run in-memory retrieval evaluations separately:

```bash
ML_MODEL_OFFLINE=true docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python -m mediamesh_ml.evaluate --output /outputs/evaluation.json
ML_MODEL_OFFLINE=true docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python -m mediamesh_ml.evaluate_video --output /outputs/video-evaluation.json
```

These evaluations do not populate the catalog. Image labels were fixed before
ranking; difficult examples and misses are retained. See [MODEL.md](MODEL.md),
[image baseline](evaluation/baseline.json), and
[video baseline](evaluation/video-baseline.json) for measured results and limits.

## Future integrated architecture

Dashed connections below are planned integration, not functionality provided by
the dummy frontend or the local fixture schema.

```mermaid
flowchart LR
    subgraph Future["Future team integration"]
        React["Production React portal"]
        Spring["Spring Boot<br/>JWT / RBAC / catalog / public APIs"]
        S3[("Private S3 media")]
    end
    subgraph ML["Reusable ML components"]
        API["Internal ML API"]
        Worker["Indexing worker<br/>Production adapters pending"]
        DB[("PostgreSQL + pgvector")]
    end
    React -.-> Spring
    Spring -.-> API
    Spring -.-> DB
    Spring -.-> S3
    React -.-> S3
    Worker -.-> S3
    API --> DB
    Worker --> DB
```

The intended integrated upload path is Spring Boot authorization → scoped S3
upload → upload completion/job creation → worker S3 retrieval → embedding/index →
READY. Search flows React → Spring Boot authorization → internal ML retrieval →
Spring metadata/status filtering and enrichment → authorized preview/download.
The React-to-S3 connection represents a backend-issued, scoped presigned URL.

Production S3 retrieval, teammate 2's job/status adapter and UUID FK agreement,
the embed-media handoff, and shared orchestration/CI remain integration work.
Step 8 adds `/internal/similar` through existing embeddings/ranking. Step 9
completes integration, performance/deployment validation, and operational setup.
Docker images, environment configuration, explicit migrations, and component
interfaces support that work; the local console/fixtures should not be deployed
as the production public application.

## Troubleshooting

| Symptom | Check / action |
|---|---|
| Script says Docker is unavailable | Start Docker Desktop, then rerun the command. |
| Frontend is not running after `manage.sh start` | Expected in ML-only mode. Use `start --with-ui` to opt in. |
| Port 8001/8002 already in use | Set `ML_API_PORT` / `ML_DEV_UI_PORT` in `.env` and start again. |
| `/health` is 200 but `/ready` is 503 | Check API logs, cached model, and vector migration. Health is not model readiness. |
| Offline startup cannot find weights | Populate the pinned model cache once with offline mode disabled, then restart with offline mode enabled. |
| Jobs remain PENDING | Start the worker profile and inspect `ml-worker` logs. The API does not process jobs. |
| LeaseExpired after a forced stop | The worker recovers the expired claim; attempts remain bounded and stale results cannot commit. |
| Job fails to read a file | Check the reference under `data/media/`, selected type, supported formats, and size/duration limits. |
| Videos cannot preview in the browser | Native browser codecs may differ from FFmpeg support; inspect whether indexing itself succeeded. |
| Samples do not appear in the dropdown | Download manifests, then reload the page. Sample binaries are not in Git. |
| Download checksum mismatch | Restore the pinned sample or explicitly review/curate a manifest update; do not silently accept changed bytes. |
| Database login fails after changing `.env` | Match `ML_DATABASE_URL` to the initialized DB credentials; environment edits do not reset an existing DB volume. |
| Worker takes time to stop | It drains current work; PostgreSQL stays up until worker/API shutdown completes through the script. |

## Code map and related documents

```text
ml-service/
  manage.sh                    # ML-only start by default; optional --with-ui
  compose.yaml                 # Standalone services and optional profiles
  Dockerfile                   # Shared runtime and development-tools targets
  .env.example                 # Local configuration examples
  src/mediamesh_ml/
    api.py, schemas.py          # Original internal search contract
    search.py, vectors.py      # Query encoding, asset ranking, transactional vectors
    embeddings.py, images.py   # Pinned CLIP and image preparation
    video.py                   # Inspection, extraction, decoded timestamps
    media.py, indexing.py      # Media adapter and reusable indexing preparation
    jobs.py, worker.py         # Local queue adapter, leases, heartbeat, retry loop
    database.py, migrate.py    # Bounded connections and explicit local migrations
    dev_ui.py                  # Separate TEST-ONLY gateway
    dataset.py, evaluate*.py   # Development download/evaluation commands
  dev-ui/                      # Dummy HTML/CSS/JS test page
  dev/                         # Local SQL fixtures and demo helpers
  evaluation/                  # Manifests, credits, fixed queries, baselines
  tests/                       # Unit/integration/opt-in real-model checks
  data/media/, outputs/        # Ignored local data and generated artifacts
```

- [Original teammate 3 assignment](../docs/team/03_PERSON_3_ML_RETRIEVAL.md)
- [Team ownership and shared contracts](../docs/team/00_TEAM_OVERVIEW.md)
- [ML integration decisions and pending handoffs](CONTRACT_NOTES.md)
- [Additional local walkthrough](LOCAL_WORKFLOW.md)
- [Dummy frontend guide](dev-ui/README.md)
- [Model requirements and observed performance](MODEL.md)
- [Evaluation/data guide](evaluation/README.md)
