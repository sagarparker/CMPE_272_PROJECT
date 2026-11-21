# MediaMesh ML service

Steps 1–3: FastAPI foundation, pinned CLIP embeddings and wildlife evaluation,
and PostgreSQL vector persistence. HTTP search, indexing pipelines, and job
processing come later. See the [original assignment](../docs/team/03_PERSON_3_ML_RETRIEVAL.md)
and [contract notes](CONTRACT_NOTES.md).

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
`ML_API_PORT` in `.env` if needed. `/ready` deliberately returns 503 until API
model/schema dependencies are wired in step 7. Docker health checks liveness.
Search/similar/embed-media HTTP routes are unimplemented (404), not mock results.

## Download samples and evaluate CLIP (step 2)

```bash
docker compose run --rm -v "$PWD/data/media:/data/media" ml-tools python -m mediamesh_ml.dataset
docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python -m mediamesh_ml.evaluate --output /outputs/evaluation.json
# Repeat after caching the model, with model network access disabled.
ML_MODEL_OFFLINE=true docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python -m mediamesh_ml.evaluate --output /outputs/evaluation-offline.json
```

The model downloads explicitly on first evaluation, never on API health/startup.
Images and text share 512-dimensional normalized vectors. No training required.
[MODEL.md](MODEL.md) records revision, performance, memory, and limitations. The
[dataset documentation](evaluation/README.md), [manifest](evaluation/manifest.json),
and [attribution](evaluation/ATTRIBUTION.md) cover 25 reviewed Commons images,
licenses, checksums, and seven fixed queries. Binaries stay outside Git. Downloads
fail on checksum mismatch. [baseline.json](evaluation/baseline.json) records the
initial real offline run. Evaluation is in-memory, separate from the future API.

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
timestamps. Best-frame-per-asset ranking comes in step 7. Approximate vector
indexing awaits scale measurements; model and unique/FK indexes exist now.
Connection, statement, and lock timeouts bound database operations.

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

Destructive fixtures refuse targets other than `postgres-test/mediamesh_test`.
Tests cover empty retrieval, repeat writes, model isolation, timestamps, FK
cascade, transaction rollback, migration checksums, concurrent replacement,
image preparation, and validation. Opt-in real-model tests check dimensions,
normalization, and elephant-vs-lion retrieval through pgvector.

## Worker and integration

```bash
docker compose --profile worker run --rm ml-worker
```

The scaffold intentionally exits 1 until step 6; no jobs are claimed. S3, real
backend jobs/statuses, and similar-media recommendations remain future work.
Internal invalid-input handling maps to 400. The error envelope awaits team
agreement. Spring Boot owns authorization, filtering, and enrichment; browsers
will not call Python directly in the integrated application.

## Configuration, storage, and shutdown

See `.env.example`; Compose uses `.env` for interpolation. Credentials are local
examples only. Change `POSTGRES_*` and `ML_DATABASE_URL` consistently. PostgreSQL
initialization variables affect new volumes only. Settings redact database
credentials in repr/validation errors. Logs use stdout/stderr.

API and worker use the same runtime image; tools add evaluation, fixtures, pytest,
and Ruff. Rebuild after source/dependency changes. The model-cache named volume
is writable by the non-root application user. Sample processing mounts media
read-only; the download command explicitly overrides that mount as writable.
Generated reports stay in ignored `outputs/`. Separate inference processes each
need model memory. CPU is the local baseline, including macOS Docker.

```bash
docker compose logs --tail 100 ml-api postgres
docker compose down
docker compose up -d --wait postgres ml-api
docker compose --profile test stop postgres-test
```

`down` preserves development database/model volumes; `--volumes` would delete
them. The test database uses ephemeral tmpfs. Joel owns shared Compose/CI;
this file is standalone. Deployment requires private networking or agreed
service authentication and external configuration/secrets. Nothing is hosted.
