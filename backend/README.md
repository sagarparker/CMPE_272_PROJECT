# Spring Boot API

The integrated API implements OIDC/JWT authentication, database roles, admin
access management, catalog metadata, signed Blob transfers, and semantic-search
orchestration. See [the root README](../README.md) to start the complete stack.

## Build and test

Requires Java 17+, Maven 3.9+, Docker, and PostgreSQL test-container access.
From this directory:

```bash
DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')" \
mvn -Dapi.version=1.44 verify
```

Tests launch isolated PostgreSQL containers, use generated signing keys for
JWT validation, and mock Blob storage. The shared acceptance test additionally exercises
real OIDC login, Azurite Blob Storage, Python indexing, and the React portal.

## Configuration

`application.yml` maps environment variables for JDBC, issuer/JWKS/audience,
Google sign-in validation, ML base URL, and Azure storage account/container.
Cloud access uses the VM managed identity. Local Compose supplies an explicitly
local-only Azurite endpoint and the fixed public emulator credential.

The configured OIDC provider must issue an API audience, stable subject, and
`sid` session identifier. Users are mapped by `(issuer, subject)` to an internal
UUID. The API requires Google broker sign-in with a verified email. The account
`sagar.parker@sjsu.edu` receives the sole ADMIN role on first Google sign-in.
Users submit `POST /api/me/access-request` with uploader/researcher roles; the
administrator lists `/api/admin/access-requests` and posts an approval or rejection
to `/api/admin/access-requests/{id}/decision`. No extra administrators or password
accounts can be created. See [account setup](../docs/ACCOUNT_SETUP.md).

Roles are loaded from the DB per request. API sessions track idle/absolute
limits (30 minutes / 8 hours); `/api/logout` revokes the session. Issued Blob SAS
URLs remain usable until expiry, as documented in the original design.

Uploads require a supported content type. `mediaType` can be omitted and is
inferred. Completion validates object size/type, locks the asset row, and
atomically creates one active job and sets PROCESSING. FAILED completion
returns 409. Upload SAS grants create-only permission, so an issued URL cannot
overwrite a source object. Browsers additionally send `If-None-Match: *`.
Size checks happen at completion, so the signed PUT does not impose a storage
quota. Decoders perform file integrity/duration validation in the worker.

Flyway owns shared schema migrations; do not run the standalone ML fixture
initializer against this catalog. API JSON examples are in
[the current contract](../docs/contracts/README.md).

## Azure deployment storage

`AzureBlobStorage` implements the shared `MediaStorage` interface. Set
`AZURE_STORAGE_ACCOUNT` and `AZURE_STORAGE_CONTAINER`. The Azure adapter uses
system-assigned managed identity, cached user-delegation keys, create-only upload
SAS and 60-second read SAS. No account keys are accepted. Outgoing identity and
Blob HTTP calls have explicit timeouts; Azure uses the JDK HTTP transport to
avoid changing Spring networking dependencies. Completion still verifies size and
media type. `InitiateAssetResponse.uploadHeaders` carries Azure's BlockBlob header.
See the [Azure runbook](../infra/deploy/README.md) for identity role scopes, CORS
and the required live-cloud validation. `s3_key` remains a historical DB column
name holding provider-neutral object keys, not a public URL.


## Search and indexing responsibilities

The API authorizes uploads and atomically records an indexing job with PROCESSING
when a verified upload completes. Python performs inference asynchronously; the
browser connection is not required for the job to finish. Originals live in Blob
Storage, not in PostgreSQL.

For search, the backend checks RESEARCHER and sends only eligible READY IDs,
query and result limit to the internal ML API. The integrated ranking is
`0.80 × visual cosine + 0.20 × metadata-text cosine`. Video uses its best sampled
frame. OpenRouter checks saved captions after ranking; it does not generate the
embedding or change the numeric score. The backend rechecks READY, applies the
configured cutoff and attaches display metadata. Preview/download use a separate
permission check and short-lived SAS request.

The OpenRouter key belongs only to ML services. It is not a Spring or browser
credential. The [root Mermaid diagrams](../README.md#system-architecture) and
[architecture guide](../docs/architecture/README.md) cover the complete path and
the differences between integrated and Azure deployment profiles.
