# MediaMesh ML service

Step 1 foundation: FastAPI liveness, environment configuration, shared Python
interfaces, and local Docker services. Search, model inference, vector migrations,
and indexing are implemented in later steps. No model or dataset is downloaded
at startup. See [contract notes](CONTRACT_NOTES.md) and the
[original assignment](../docs/team/03_PERSON_3_ML_RETRIEVAL.md).

## Local Docker setup

Requires a running Docker engine and Docker Compose. Run commands from
`ml-service/`. Host Python, PostgreSQL, and FFmpeg installations are unnecessary.
Initial image/dependency downloads require internet access.

```bash
cd ml-service
mkdir -p data/media
cp .env.example .env
docker compose build ml-api ml-tools
docker compose up -d --wait postgres ml-api
curl --fail http://127.0.0.1:8001/health
```

Expected liveness response: `{"status":"ok"}`. Local interactive API docs are at
`http://127.0.0.1:8001/docs`. The API port is bound to localhost; PostgreSQL has
no published port. Change `ML_API_PORT` in `.env` if 8001 is occupied.

`GET /ready` deliberately returns **503** until real model/database/schema
readiness checks are connected. Docker health currently checks liveness only.
Search/similar/embed-media routes are not implemented and return 404, rather
than fabricated results. Request-validation errors map to 400 to follow the
team contract. The provisional error envelope is documented in contract notes.

## Verification

```bash
docker compose run --rm ml-tools pytest
docker compose run --rm ml-tools ruff check .
docker compose run --rm ml-tools ruff format --check .
docker compose run --rm ml-tools uv lock --check
docker compose run --rm ml-tools ffmpeg -version
docker compose run --rm ml-tools ffprobe -version
docker compose exec postgres psql -U mediamesh -d mediamesh -c "SELECT name, default_version FROM pg_available_extensions WHERE name = 'vector';"
```

Tests use no external services/model in step 1. The image includes pgvector,
but does not enable the extension or create production tables yet; those belong
to the explicit V3xx migration in step 3. No assets/job fixture schema exists yet.

The API, tools, and future worker share the same package and locked dependencies.
Tools use a separate build target including development dependencies; the runtime
image omits pytest/Ruff. Rebuild images after source/dependency changes.

## Worker scaffold

The worker service is opt-in until step 6:

```bash
docker compose --profile worker run --rm ml-worker
```

This command intentionally exits 1 with an explanation. It does not claim or
process jobs. No idle container is presented as a functioning worker.

## Configuration and storage

Configuration uses `ML_` variables; see `.env.example`. Compose reads `.env` for
interpolation. Do not commit `.env`. The included database credentials are for
local development only. If changing database credentials, update both
`POSTGRES_*` and `ML_DATABASE_URL`; PostgreSQL initialization variables affect
new data volumes only. Settings redact the database URL in representations and
validation errors. Logs go to the container's stdout/stderr.

Paths inside containers are `/data/media` and `/data/models`. Model caches use a
named volume and sample media is a read-only bind mount. The image pre-creates
the model directory for its non-root application user. Temporary files will use
container-local temporary storage with cleanup when indexing is implemented.
API and worker run separate processes and will each need model memory. CPU is
the baseline, including on macOS Docker. Exact model revision and embedding
dimensions are intentionally not frozen until step 2.

The standalone Compose file stays in this directory; shared root orchestration
and CI integration belong to teammate 4. Internal services must remain private
or use an agreed service-authentication mechanism when deployed. The future S3
adapter will consume server-side credentials, never browser credentials.

## Stop and restart

```bash
docker compose logs --tail 100 ml-api postgres
docker compose down
docker compose up -d --wait postgres ml-api
```

`down` retains the database and model-cache volumes. Do not add `--volumes`
unless intentionally deleting the local database and model cache. Downloaded
sample media remains in the ignored `data/` directory. Nothing is hosted or
published by these commands beyond the localhost API.
