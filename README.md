# MediaMesh — Enterprise Media Discovery for National Geographic

> **Status:** Integrated MVP implemented; local acceptance verified.
> **Context:** CMPE 272 student project. National Geographic is a **hypothetical enterprise customer scenario**; this is not an official NatGeo product or integration.

MediaMesh is a secure, searchable media library for editorial teams. A wildlife photographer or archive assistant can upload photographs and documentary clips to private object storage. A footage researcher can then search using natural language—without knowing filenames—and retrieve authorized photos or approximate matching video moments. A media administrator decides who can upload and who can search.

**Example:** A researcher preparing a feature on elephants searches for **“elephants drinking at a watering hole at sunset.”** MediaMesh finds visually similar photographs and sampled frames from documentary clips, and displays uploader-provided species, location, capture date, contributor and usage notes.

## Run the integrated application

Start Docker Desktop, then run:

```bash
./infra/start.sh
```

Open **http://localhost:8080**. First start downloads EmbeddingGemma 2 and the
Ollama caption model into Docker volumes. Track model setup with
`./infra/manage.sh logs gemma-embed ollama-init`.

Local demo accounts: `admin`, `uploader`, `researcher`, `employee`; all use
`local-demo-only`. These are public local fixtures. Only `admin` gets a role
automatically. Sign in as the other users once so they appear in the Admin
screen, then assign `UPLOADER` and `RESEARCHER`. Use separate browser profiles
or sign out between accounts. Admin does not implicitly receive other roles.

For a populated nature showcase, run `./infra/seed-demo.sh` using Node.js 24
after starting the stack. It loads **48 photos and two videos** across wildlife,
plants, oceans, marine life, birds and landscapes, with a dedicated uploader for
each and a separate researcher. See the [demo accounts, setup and walkthrough](infra/demo/README.md)
and [media attribution](ml-service/evaluation/DEMO_ATTRIBUTION.md).

See [the runbook](infra/README.md) for testing and Azure deployment.
Read [the implementation walkthrough](docs/IMPLEMENTATION.md)
to learn how the checkpoints fit together, and [the API contract](docs/contracts/README.md)
for routes and JSON examples. The historical team assignments below describe
workstream scope; Mathew now owns all workstreams.

The [course slide checklist](docs/COURSE_CHECKLIST.md) maps each security and
reliability requirement to implementation, tests, presentation evidence, and
account-owner steps that still need verification.

### Local Compose services

Use the service names below with `./infra/manage.sh`.

| Service | Component | When it runs |
| --- | --- | --- |
| `frontend` | React portal at `http://localhost:8080`, including the `/auth` proxy to Keycloak | Default stack |
| `backend` | Spring Boot API for the media catalog, access control, and search | Default stack |
| `postgres` | PostgreSQL with pgvector for catalog metadata, jobs, and embeddings | Default stack |
| `keycloak` | Local identity provider for sign-in and account provisioning | Default stack |
| `azurite` | Azure Blob Storage emulator at `http://localhost:10000` | Default stack |
| `blob-init` | Configures the Blob container and CORS before the backend starts | One-time startup job |
| `gemma-embed` | EmbeddingGemma 2 text and image encoders | Default stack |
| `ollama` | Vision captions and query-to-caption verification | Default stack |
| `ollama-init` | Installs the configured Ollama model if it is missing | One-time startup job |
| `ml-api` | FastAPI service for semantic search and model inference | Default stack |
| `ml-worker` | Background worker that indexes uploaded images and videos | Default stack |
| `prometheus` | Metrics and alert rules at `http://localhost:9090` | Default stack |
| `postgres-test` | Isolated PostgreSQL with pgvector for integration tests | `test` profile |
| `ml-tests` | Python lint and test runner | `test` profile |

```bash
./infra/manage.sh start ml-worker
./infra/manage.sh stop ml-worker
./infra/manage.sh restart ml-worker
./infra/manage.sh logs ml-worker
./infra/manage.sh status
```

Starting a service also starts its required dependencies. Stopping a service
keeps its container, logs, and data volumes. Run `./infra/manage.sh stop` to
stop the stack or `./infra/manage.sh help` for all commands. The `test`
profile is used by `./infra/check.sh`.

## Reliability and observability

For the final Azure student demo, use the separate [Azure VM + Blob Storage runbook](infra/deploy/README.md).
It includes HTTPS, fresh identities, managed-identity storage access, launch checks,
backups and recovery. The localhost stack is not a public deployment profile.

Semantic search now has a **99% / rolling 30-day SLO**: HTTP 200 within two
seconds for valid researcher requests. Prometheus at **http://localhost:9090**
shows search SLI, error-budget policies, two-window burn alerts, and ML
circuit-breaker/bulkhead metrics. A new installation reports partial history;
zero traffic does not imply 100% availability. No real paging receiver exists.

- [SLO, error budget, and incident runbook](docs/observability/SLO_ERROR_BUDGET.md)
- [Circuit breaker, bulkhead, error boundary, and local demonstrations](docs/observability/RESILIENCE_PATTERNS.md)

## MVP at a glance

| Capability | Scope |
|---|---|
| Enterprise authentication | OIDC single sign-on; JWT-protected Spring Boot APIs; defined access/session expiration |
| Admin-controlled RBAC | `ADMIN`, `UPLOADER`, `RESEARCHER` roles; role changes checked against current DB assignments |
| Media catalog | Photo and short video uploads; editorial metadata; processing states |
| Media storage | Private Azure Blob container for deployment; short-lived SAS upload/access links; Azurite locally |
| Natural-language discovery | CLIP text/image embedding similarity; video search using sampled keyframes |
| Vector retrieval | PostgreSQL + pgvector; authorized, ready assets only |
| Recommendation | Basic related-media suggestions from vector similarity (no behavioral personalization) |
| Delivery | React frontend, Spring Boot API, Python ML service, Docker Compose, Jenkins CI |

**Explicitly out of scope for MVP:** custom distributed storage/replication, Kubernetes, Kafka/SQS, service mesh, LLM agent/MCP, native audio search/transcription, multi-tenant SaaS, comprehensive digital-rights clearance, per-collection confidential-content ACLs. Media rights notes are advisory; they do not authorize publication.

## System architecture

```mermaid
flowchart TB
    STAFF["NatGeo editorial staff (browser)"]
    BLOB[("Private Azure Blob container")]
    subgraph VM["Azure VM - Docker Compose, one container per service"]
        EDGE["Caddy HTTPS gateway"]
        WEB["React portal (nginx)"]
        IDP["Keycloak SSO - password + authenticator"]
        API["Spring Boot API - JWT, RBAC, catalog, audit"]
        ML["Python search service (ml-api)"]
        WORK["Python indexing worker (ml-worker)"]
        PG[("PostgreSQL and pgvector")]
        PROM["Prometheus"]
    end

    STAFF -->|HTTPS| EDGE
    EDGE -->|Sign-in pages| IDP
    EDGE --> WEB
    WEB -->|/api requests with access JWT| API
    API -->|Verify tokens, create and delete accounts| IDP
    IDP -->|Identity data| PG
    API -->|Read and write records| PG
    API -->|Semantic search| ML
    ML -->|CLIP text vector, pgvector ranking| PG
    API -->|Return short-lived SAS URL| WEB
    STAFF -->|Upload or preview media with SAS| BLOB
    WORK -->|Claim jobs, store vectors and status| PG
    WORK -->|Read original, write video playback copy| BLOB
    API -->|Sign SAS, verify uploads| BLOB
    PROM -->|Scrape search metrics| API
```

The indexing worker runs CLIP in its own process; it does not call the search
service. The backend and worker reach Blob Storage with the VM's managed
identity, so no storage key exists. See the [component diagram](docs/architecture/mediamesh-architecture.png)
and the [detailed deployment reference](docs/architecture/azure-deployment-architecture.html).

**Security boundary:** Only the Caddy gateway is public (ports 80/443); Keycloak's admin console, metrics, the database and the Python services are not reachable from the internet. The browser never accesses internal Python endpoints directly. The backend validates JWTs and verifies current role assignments for each protected action. Media objects are private. SAS URLs are scoped and short-lived (15-minute create-only upload, 60-second read); role revocation cannot invalidate an already-issued URL before it expires.

## User roles

| Action | ADMIN | UPLOADER | RESEARCHER | Signed-in unassigned |
|---|:---:|:---:|:---:|:---:|
| Create accounts, assign roles, delete users | Yes (administrator accounts: primary admin only) | No | No | No |
| Upload photos/video | Only with UPLOADER role | Yes | No | No |
| Edit own asset metadata | Only with UPLOADER role | Yes | No | No |
| Search media | Only with RESEARCHER role | No | Yes | No |
| Preview / download | Only with RESEARCHER role | No | Yes | No |

Roles can be combined. There is no self-registration: an administrator creates each account with one role and a one-time temporary password; the first sign-in forces a new password and authenticator (TOTP) enrollment. The configured bootstrap subject is the primary administrator; only it can create, grant, remove or delete administrators. See [account setup](docs/ACCOUNT_SETUP.md).

## Core workflows

### 1. Employee sign-in

```mermaid
sequenceDiagram
    actor Employee
    participant UI as React Portal
    participant IdP as Keycloak
    participant API as Spring Boot
    participant DB as PostgreSQL
    Employee->>UI: Open MediaMesh
    UI->>IdP: OIDC Authorization Code + PKCE
    IdP->>Employee: Password + authenticator code
    IdP-->>UI: Authenticated session / tokens
    UI->>API: GET /api/me with access JWT
    API->>API: Validate signature, issuer, audience, expiry
    API->>DB: Match (issuer, subject) to the admin-created user, read roles
    DB-->>API: Current roles
    API-->>UI: User profile + roles
    Note over UI,API: Expired/invalid access token returns 401, renew or reauthenticate
```

### 2. Admin creates accounts and assigns access

```mermaid
sequenceDiagram
    actor Admin
    participant UI as React Portal
    participant API as Spring Boot
    participant IdP as Keycloak
    participant DB as PostgreSQL
    Admin->>UI: Create account (username, email, role)
    UI->>API: POST /api/admin/users
    API->>API: Verify JWT + ADMIN (ADMIN role: primary admin only)
    API->>IdP: Create user, temporary password, require password change + TOTP
    API->>DB: Record user, role and audit event
    API-->>UI: Temporary password, shown once
    Admin->>UI: Change roles or delete a user
    UI->>API: PUT roles / DELETE user
    API->>DB: Replace roles or remove roles and sessions, audit
    API->>IdP: Delete login (user deletion only)
    Note over API,DB: Changes apply to the next API authorization check
```

### 3. Uploader adds wildlife footage

```mermaid
sequenceDiagram
    actor Uploader
    participant UI as React Portal
    participant API as Spring Boot
    participant BLOB as Private Azure Blob Container
    participant DB as PostgreSQL
    participant Worker as Python Indexer
    Uploader->>UI: Select file, enter species/location/rights notes
    UI->>API: POST /api/assets/initiate (JWT)
    API->>API: Require UPLOADER
    API->>DB: Create asset status UPLOADING
    API-->>UI: Presigned upload URL + asset ID
    UI->>BLOB: PUT media using short-lived URL
    UI->>API: POST complete upload endpoint
    API->>BLOB: Verify uploaded object
    API->>DB: Create retryable indexing job
    API-->>UI: 202 PROCESSING
    Worker->>DB: Claim pending job
    Worker->>BLOB: Read image/video
    Worker->>Worker: CLIP image / sampled frame embeddings
    Worker->>BLOB: Videos: write browser-safe H.264 playback copy
    Worker->>DB: Store vectors, set READY
```

### 4. Researcher searches by natural language

```mermaid
sequenceDiagram
    actor Researcher
    participant UI as React Portal
    participant API as Spring Boot
    participant ML as Python Search
    participant DB as PostgreSQL
    Researcher->>UI: Search "elephants at a watering hole"
    UI->>API: POST /api/search with access JWT
    API->>API: Require RESEARCHER
    API->>ML: Embed query and retrieve candidate asset IDs
    ML->>DB: pgvector similarity lookup
    DB-->>ML: Ranked IDs and video timestamps
    ML-->>API: Candidate matches
    API->>DB: Filter READY assets + metadata constraints
    API-->>UI: Authorized results with title, metadata and score
```

### 5. Authorized preview/download

```mermaid
sequenceDiagram
    actor Researcher
    participant UI as React Portal
    participant API as Spring Boot
    participant DB as PostgreSQL
    participant BLOB as Private Azure Blob Container
    Researcher->>UI: Open matching asset
    UI->>API: POST asset access URL endpoint
    API->>API: Validate JWT and RESEARCHER role
    API->>DB: Ensure asset exists and is READY
    Note over API: Video previews use the H.264 playback copy, downloads use the original
    API-->>UI: Short-lived Blob SAS URL
    UI->>BLOB: GET media using presigned URL
    BLOB-->>UI: Photo/video preview
```

## Technology stack

| Layer | Chosen MVP stack | Notes |
|---|---|---|
| Web UI | React | Role-aware editorial portal |
| Enterprise API | Java / Spring Boot / Spring Security | JWT and RBAC enforcement, asset catalog, orchestration |
| SSO | Keycloak 26 (OIDC, Authorization Code + PKCE) | Password + authenticator (TOTP); admin-created accounts only |
| Gateway | Caddy (deployment), nginx (portal) | HTTPS with Let's Encrypt; only ports 80/443 public |
| Media storage | Azure Blob Storage | Private container; create-only upload SAS and read-only preview/download SAS |
| Structured database | PostgreSQL | Users, roles, assets, indexing jobs, audit events |
| Vector database | pgvector | Vectors in the existing PostgreSQL database |
| ML retrieval | Python / FastAPI, Pydantic, Uvicorn, Sentence Transformers / CLIP | Standalone multimodal embedding and semantic retrieval service |
| Video indexing | FFmpeg | Sample keyframes, report approximate matching timestamp; write H.264 playback copy |
| Monitoring | Prometheus | Search SLI, error budget and burn-rate rules |
| Deployment | Docker Compose on one Azure VM | `compose.deploy.yaml`; `compose.yaml` for local runs; single VM, not highly available |
| CI | Jenkins + GitHub Actions | Build, unit and integration tests |

## Repo organization

```text
Media-Mesh/
├── README.md
├── docs/
│   ├── architecture/           # Component diagram and deployment reference
│   ├── design/                 # NatGeo stakeholder architecture and design background
│   ├── team/                   # Shared plan plus four individual task assignments
│   └── contracts/              # Contract freeze and integration guidance
├── backend/                    # Teammates 1 and 2: separate Java packages
├── ml-service/                 # Teammate 3: embedding, indexing and retrieval
├── frontend/                   # Teammate 4: React portal
├── infra/                      # Teammate 4: local/deployment definitions
├── compose.yaml                # Local stack (Azurite, Keycloak dev realm)
├── compose.deploy.yaml         # Azure VM deployment
├── .github/workflows/          # GitHub Actions CI
└── Jenkinsfile                 # Jenkins pipeline
```

**The source directories now contain the integrated implementation.** Original team documents remain as design and ownership history; use the runbook and current API contract for executable instructions.

## Team ownership

| Teammate | Exclusive responsibility | Task document |
|---|---|---|
| Sonit | Enterprise identity, JWT, RBAC, admin APIs, audit | [Identity & RBAC](docs/team/01_PERSON_1_IDENTITY_RBAC.md) |
| Mathew | Media catalog, metadata APIs, S3, indexing job lifecycle | [Media Backend & S3](docs/team/02_PERSON_2_MEDIA_S3_BACKEND.md) |
| Sagar | CLIP embeddings, retrieval, video keyframes, pgvector integration | [ML & Search](docs/team/03_PERSON_3_ML_RETRIEVAL.md) |
| Joel | React portal, local orchestration, Jenkins, integration demo | [Frontend & DevOps](docs/team/04_PERSON_4_FRONTEND_DEVOPS.md) |

Start with the [shared team overview and API contracts](docs/team/00_TEAM_OVERVIEW.md). Shared interface changes require a PR review before modifying another person's owned code.

## Project documentation

- [NatGeo stakeholder system design](docs/design/NATGEO_STAKEHOLDER_DESIGN.md) — detailed use case, exact metadata, decisions, five sequence flows.
- [Enterprise design background](docs/design/ENTERPRISE_DESIGN_BACKGROUND.md) — prior design rationale and alternatives.
- [Team work allocation](docs/team/00_TEAM_OVERVIEW.md) — ownership rules, routes, sample request/response payloads, checkpoints.
- [Integration guidelines](docs/contracts/README.md) — source ownership and contract freeze checklist.

## Acceptance demonstration

1. Employee signs in using OIDC and initially has no permissions.
2. Administrator grants `UPLOADER` and/or `RESEARCHER` role; revocation works without relying on stale JWT role claims.
3. Uploader sends a NatGeo-style wildlife photograph and a short documentary clip to private Blob Storage and supplies source metadata.
4. Indexing transitions from `UPLOADING` → `PROCESSING` → `READY`; duplicate completion does not double-index content.
5. Researcher searches **“elephants drinking at a watering hole at sunset”** and finds relevant images or video frames.
6. Researcher can preview/download authorized assets through short-lived URLs.
7. A user without permission receives `403`; an expired or invalid token receives `401`.
8. Docker local setup and Jenkins test pipeline are documented and demonstrable.

## Implemented MVP decisions

- Keycloak OIDC with Authorization Code + PKCE; JWT signature, issuer, audience
  and timestamp checks; current roles loaded from PostgreSQL on every request.
- Public local demo identities; one explicit bootstrap (primary) admin subject.
  In the cloud, accounts are created by an admin with a temporary password and
  mandatory TOTP enrollment. API
  sessions enforce 30-minute idle and 8-hour absolute limits; logout revokes
  the local session and ends the provider session. Access JWTs last 15 minutes.
- Azure VM + private Blob Storage for cloud deployment; Azurite Blob Storage is the local demo fixture.
- JPEG, PNG, MP4 and QuickTime; 100 MB maximum at completion and 180-second
  video duration during indexing. PUT URLs expire in 15 minutes; GET in 60 seconds.
- Frozen CLIP model revision and 512-dimensional normalized vectors. Workers
  invoke shared Python indexing functions directly; no embed-media HTTP endpoint.
- Related media uses one reference frame for videos. Search filters are applied
  to READY catalog IDs before similarity ranking. Exact search targets the small
  MVP catalog; large archives need database-side filtered vector indexing.

## Security and project hygiene

Never commit secrets, JWTs, OAuth credentials, Azure credentials/storage keys, private media objects, user records or trained model/data caches. Use environment variables and example configuration only. Upload rights notes are not a substitute for formal media licensing checks.

See [Azure Blob migration checkpoints](docs/AZURE_BLOB_MIGRATION.md) for the storage implementation and preservation of existing demo media.

See [account setup](docs/ACCOUNT_SETUP.md) for creating researcher, uploader and administrator logins and the first sign-in steps.

See [Azure demo data transfer](docs/AZURE_DEMO_DATA_TRANSFER.md) for the source checks, cloud accounts, import commands, validation and recovery steps.
