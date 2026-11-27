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
bootstrap admin subject, ML base URL, and Azure storage account/container.
Cloud access uses the VM managed identity. Local Compose supplies an explicitly
local-only Azurite endpoint and the fixed public emulator credential.

The configured OIDC provider must issue an API audience, stable subject, and
`sid` session identifier. Users are mapped by `(issuer, subject)` to an internal
UUID. The explicitly configured `BOOTSTRAP_ADMIN_SUBJECT` gets ADMIN once and is the
primary administrator: it always keeps ADMIN and is the only account that may
grant, remove or create ADMIN. `POST /api/admin/users` (any ADMIN) creates a
Keycloak identity with a temporary password plus required password-change and
TOTP actions, records the user and its single role, and returns the password
once. Other admins may create only RESEARCHER or UPLOADER accounts.

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
