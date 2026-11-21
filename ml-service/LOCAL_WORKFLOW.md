# Local worker and search walkthrough

Run commands from `ml-service/`. This workflow uses local fixtures, Docker, and
cached CLIP weights; it does not provision hosting or use S3.

## Start and stop with one script

From the repository root:

```bash
./ml-service/manage.sh start
./ml-service/manage.sh start --with-ui
./ml-service/manage.sh stop
./ml-service/manage.sh restart
./ml-service/manage.sh restart --with-ui
./ml-service/manage.sh status
./ml-service/manage.sh start ml-api
./ml-service/manage.sh stop ml-worker
./ml-service/manage.sh logs
./ml-service/manage.sh logs ml-worker
```

The executable script also works from any other directory using its absolute
path. Default startup manages PostgreSQL, the ML API, and worker only, and stops the
dummy frontend if it is running. Add `--with-ui` to start that optional test UI.
Named `start SERVICE` / `stop SERVICE` / `restart SERVICE` operations are also
available for postgres, ml-api, ml-worker, and ml-dev-ui.
Core mode builds only the runtime image and uses temporary runtime containers
with read-only local SQL fixtures for bootstrap, rather than the tools image.
`start` reuses Docker build layers, initializes the guarded local fixtures,
loads/caches the pinned model, and waits for readiness. The first run may download
images/dependencies/model weights; existing media are not reindexed and samples
are not downloaded. Existing `.env` settings are preserved and used by Compose.
An explicitly configured offline model mode requires an already-populated cache.

`stop` drains the worker before stopping PostgreSQL. It retains containers,
database volumes, embeddings, cached weights, and uploaded files. The optional
test database is not managed by this script. Docker Desktop must already be
running. `logs` follows output until Ctrl+C without stopping services. Running
`start` after `stop` restores the same stored data. The script prints the actual
URLs for the selected mode, including configured custom ports. Default logs
follow core services; request `logs ml-dev-ui` explicitly for the optional UI.

## First setup or update

Preserve an existing `.env`; copy `.env.example` only on first setup.

```bash
mkdir -p data/media outputs
# First setup only: cp .env.example .env
docker compose build ml-api ml-tools
docker compose up -d --wait postgres
docker compose run --rm ml-tools python -m mediamesh_ml.migrate --local-fixture
docker compose run --rm ml-tools python -m mediamesh_ml.jobs init

# Explicit model download/cache validation (no training).
docker compose run --rm ml-tools python -m mediamesh_ml.embeddings

# Download the attributed image/video samples once. Later runs verify cached bytes.
docker compose run --rm ml-tools python -m mediamesh_ml.dataset
docker compose run --rm ml-tools python -m mediamesh_ml.dataset --manifest evaluation/video-manifest.json

# Separate long-running model instances, using the populated cache offline.
ML_MODEL_OFFLINE=true docker compose --profile worker up -d --wait ml-api ml-worker
curl --fail http://127.0.0.1:8001/ready
```

The worker profile is opt-in. Starting only the API does not start the worker.
API startup loads its model once; the worker loads its model before claiming
jobs. `/health` checks process liveness, `/ready` checks model and vector schema/
database readiness. A failed model load leaves readiness/search at 503; fix the
cache/config and restart the API. A temporary database outage can recover without
a model reload. Containers need to remain running for automatic job processing.

## Optional browser console

```bash
ML_MODEL_OFFLINE=true docker compose --profile worker --profile ui up -d --wait ml-api ml-worker ml-dev-ui
```

Open **http://127.0.0.1:8002** to upload/index files, index samples, inspect jobs,
run the retry test, and search with image/video previews. The same worker and
ML API perform the work. See [dev-ui/README.md](dev-ui/README.md). The console is
local-only and does not implement the future Spring Boot/React integration.

## Repeatable demonstration

```bash
docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python dev/demo.py --retry-demo --output /outputs/end-to-end.json
```

The demo registers two fixed local asset IDs, queues a wildlife photo and video,
waits for the worker, and calls HTTP search through the private Compose network.
The optional retry demo queues a missing photo, observes a failed first attempt,
then copies `elephant-02.jpg` to its reference so a subsequent attempt succeeds.
Use the default retry delay (at least one second) for this demonstration. The
small copied input is retained under `data/media/` so its READY fixture remains
valid; its source/credits are the `elephant-02` image in the attribution manifest.
All binary files and generated reports remain ignored by Git.

The tools service deliberately mounts media writable for downloads and this
fixture; API and worker mounts stay read-only.

The script checks that the expected assets are retrieved. The test suite also
asserts exact rank, null image timestamps, and numeric video timestamps. Repeating
the demo reindexes the fixed image/video IDs without creating duplicate vectors.
Each optional retry demo creates a distinct local test asset/job for inspection.

## Queue your own local media

Place files under host `data/media/`. The worker sees `/data/media` read-only.
Register a UUID in the standalone fixture only, then enqueue it:

```bash
docker compose run --rm ml-tools python dev/register_asset.py 00000000-0000-4000-8000-000000000701
docker compose run --rm ml-tools python -m mediamesh_ml.jobs enqueue --asset-id 00000000-0000-4000-8000-000000000701 --reference elephant-02.jpg --media-type image
# Use the returned job UUID:
# docker compose run --rm ml-tools python -m mediamesh_ml.jobs status JOB_UUID
```

For a clip, pass `--media-type video`. The enqueue command returns immediately;
the daemon handles inference, persistence, and local status. Identical active
jobs deduplicate. A conflicting active reference is rejected. Enqueueing again
after a terminal job explicitly requests reindexing. The backend's upload
completion idempotency remains a separate future integration contract.

Nothing watches the directory: copying a file alone does not enqueue a job.
Index only new/changed media. Searches and service restarts reuse stored vectors.
Future Spring Boot upload completion will create jobs automatically through the
agreed production adapter; private-S3 media retrieval is still future work.

## Search contract

```bash
curl --fail http://127.0.0.1:8001/internal/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"a herd of bison grazing in a green valley","limit":10}'
```

```json
{
  "matches": [
    {"assetId": "00000000-0000-4000-8000-000000000501", "score": 0.35, "frameTimestampSeconds": 18.385}
  ]
}
```

The response is illustrative; scores, timestamps, and other candidates depend
on indexed content. Original route, nesting, and field names are unchanged.
Images use null timestamps. Each asset occurs once, with its highest-scoring
frame; ties use timestamp then asset UUID deterministically. Ranking happens
before limiting, so a long video cannot crowd out other assets.

Defaults chosen for local development: limit 20, maximum 100, query maximum
1,000 characters after trimming. Empty/non-string queries, invalid limits, extra
fields, malformed JSON, and over-budget CLIP text return 400. The model allows
77 tokens including special tokens; overlong queries are rejected, not silently
truncated. Default/maximum values and the `{error:{code,message}}` envelope remain
integration decisions to confirm with the team. Scores can be negative and are
not probabilities. Dependency failures return 503, not successful empty results.
An empty index returns 200 with `{"matches":[]}`. OpenAPI documents 400 rather
than FastAPI's default 422.

No S3 URLs, embeddings, metadata, or user information are returned. Spring Boot
owns authorization, READY/metadata filtering, enrichment, and media access. These
are internal candidates; the local Python service does not implement employee
JWT/RBAC. Keep it private when integrated. `/internal/similar` remains step 8.
`/internal/embed-media` is still a pending handoff: worker and API share Python
embedding code, but no unapproved HTTP payload has been invented.

## Local queue safety and production boundary

`ml_dev.index_jobs` and `ml_dev.asset_states` are explicit, guarded development
fixtures. They do not alter production media tables. `jobs init` refuses a
production asset schema. This is not a claimed implementation of Mathew's V2xx
job schema or lifecycle. The production adapter must agree on fields, retries,
leases, asset states, S3 references, and atomic completion before integration.

Claiming uses `FOR UPDATE SKIP LOCKED`, increments attempts, and assigns a fresh
lease token. A heartbeat renews while inference runs outside database transactions.
Expired claims retry with bounded exponential delay, or fail when attempts are
exhausted. Completion verifies ownership and commits vectors/job success/local
READY state in one transaction. Failed writes roll back all three. Stale workers
cannot complete/fail a reassigned claim. Computation may repeat after lease loss;
committed vector replacement remains idempotent. Permanent invalid media fails
without retries; missing files, temporary I/O/inference failures, and decoder
timeouts can retry. Error codes are stored without private paths or credentials.
SIGTERM stops new claims and lets the current job finish; a forced stop recovers
through lease expiry. Docker allows 150 seconds to drain.

## Verify and stop

```bash
docker compose --profile test up -d --wait postgres-test
docker compose run --rm -e ML_RUN_MODEL_TESTS=1 -e ML_RUN_VIDEO_TESTS=1 -e ML_TEST_DATABASE_URL=postgresql://mediamesh:local-test-only@postgres-test:5432/mediamesh_test ml-tools pytest
docker compose run --rm ml-tools ruff check .
docker compose run --rm ml-tools ruff format --check .
docker compose run --rm ml-tools uv lock --check
docker compose --profile worker logs --tail 100 ml-worker ml-api
docker compose --profile test stop postgres-test
docker compose --profile worker --profile ui down
```

The test database is separate and ephemeral. Destructive fixtures refuse the
development database. `down` preserves model/database volumes; do not add
`--volumes` unless intentionally deleting them. The Docker runtime and tools
share heavy dependency layers; source changes no longer reinstall PyTorch, and
wheel-download caches are not baked into the application image.
