# MediaMesh repository guidance

## Project state

This repository implements the Python ML service, Spring media catalog, React frontend and Docker Compose infrastructure. Azure Blob Storage is the media store, with Azurite locally. Read `README.md`, `docs/team/00_TEAM_OVERVIEW.md`, and `docs/contracts/README.md` before changing integration contracts.

## Commands

Run component commands from the repository root unless a command says otherwise.

### Spring backend

Java 17 and Maven 3.9+ are required.

```bash
cd backend
mvn test                                  # full backend test suite
mvn -Dtest=AssetServiceTest test          # one test class
mvn -Dtest=AssetServiceTest#completeRejectsAnotherUsersAsset test  # one test method
mvn package                               # build the application JAR
mvn spring-boot:run                       # run locally with PostgreSQL/Azure configuration
```

No separate backend lint or formatting command is configured.

The backend README's local run example requires PostgreSQL and Azure configuration:

```bash
DATABASE_URL=jdbc:postgresql://localhost:5432/mediamesh \
DATABASE_USERNAME=mediamesh DATABASE_PASSWORD=mediamesh \
AZURE_STORAGE_ACCOUNT=yourstorageaccount AZURE_STORAGE_CONTAINER=mediamesh mvn spring-boot:run
```

### Python ML service

Python 3.11 and `uv` are required; Docker is required for the full local stack.

```bash
cd ml-service
uv run pytest                                      # full local pytest suite
uv run pytest tests/test_api.py                    # one test module
uv run pytest tests/test_api.py::test_empty_search_and_default_limit  # one test
uv run ruff check .
uv run ruff format --check .
uv lock --check
```

Docker Compose is the integration environment:

```bash
./ml-service/manage.sh start
./ml-service/manage.sh start --with-ui
./ml-service/manage.sh status
./ml-service/manage.sh logs
./ml-service/manage.sh stop
```

The local API runs on port 8001 and the optional test UI on port 8002 by default. Start the worker explicitly through the management script; the API-only mode does not process jobs. For model/database/video test coverage, use the Docker test workflow documented in `ml-service/LOCAL_WORKFLOW.md`.

## Architecture

- The public browser API is Spring Boot under `/api/**`. Spring Security validates JWTs and checks current database role assignments; the React browser must not call the private ML service directly.
- The ML service is a separate FastAPI process exposing private `/internal/**` routes for embeddings/search. It uses PostgreSQL plus pgvector and a fixed CLIP model revision.
- Media upload is orchestrated by Spring: create an asset in `UPLOADING`, issue a private Blob create-only SAS URL, verify completion, atomically move to `PROCESSING`, and create at most one active `index_jobs` row.
- An indexing worker claims jobs, reads image/video media, creates CLIP embeddings or sampled video-frame embeddings, and persists vectors plus the final asset state. Search returns asset IDs and optional frame offsets; Spring owns authorization, READY/metadata filtering, and media access URL enrichment.
- PostgreSQL is shared by the catalog, jobs, identity/RBAC, and vectors. Flyway migrations are numbered by owner: `V1xx` identity/RBAC, `V2xx` assets/jobs, `V3xx` vectors.
- The ML stack uses fixed development fixtures and guarded local tables for standalone development; do not treat them as production integration without implementing/using the agreed Spring production adapter.

## Repository conventions

- Respect exclusive ownership boundaries. Shared routes, DTO field names, role names, statuses, error codes, shared Spring configuration, Compose, and CI require a reviewed interface change. The route contracts are in `docs/team/00_TEAM_OVERVIEW.md`.
- The roles are `ADMIN`, `UPLOADER`, and `RESEARCHER`; roles may be combined. Authorization is `401` for unauthenticated/expired/invalid tokens and `403` for authenticated insufficient permissions.
- Asset states are `UPLOADING`, `PROCESSING`, `READY`, and `FAILED`. Searchable assets must be `READY` in production filtering.
- Use stable UUID principal names at the Spring/ML/database boundary. An authenticated principal must be a UUID, and asset ownership checks must use that owner ID.
- Keep asset upload and indexing transitions idempotent. Duplicate completion must not create duplicate jobs or vectors.
- Public code must not return storage credentials, private object references/paths, model secrets, database credentials, embeddings, or internal user data. Presigned URLs are backend-generated and short-lived.
- Keep private Blob and browser credentials separate. ML uses private mounted media or private object references according to the integration contract, never public browser access.
- ML configuration is environment-based through `ML_*` variables and Pydantic settings. Compose has the pinned model name/revision and 512-dimensional embeddings; vector schema and model configuration must remain compatible.
- ML API error handling is deliberately an `{ "error": { "code", "message" } }` envelope. Invalid input is `400`, dependencies/search failures are `503`, and `/health` is liveness only while `/ready` checks dependencies.
- Never commit `.env` credentials, Azure account keys, JWTs, private media, model/data caches, or generated demo output. Preserve existing `.gitignore` behavior and seeded local fixture safety.
