# MediaMesh implementation walkthrough

This guide follows the checkpoints used to complete the original four-person
MVP. The root README gives startup instructions; `infra/README.md` gives the
runbook. The old team documents are historical task assignments.

## Checkpoint 1: connect the boundaries

The starting code had a Java upload flow and a standalone Python CLIP service.
They used different job tables and media sources, so completing an upload
could not cause indexing. There was no real authentication or React portal.

We kept the existing Spring/React/PostgreSQL/Python design, selected Keycloak
as the local OIDC provider, and added a root Compose stack. LocalStack is the
local S3 emulator; AWS uses the same SDK interfaces with normal endpoints.
The frontend and browser uploads use localhost endpoints, while containers
use internal service names. A signed URL must be signed for its browser-visible
host; changing the host after signing would invalidate its signature.

## Checkpoint 2: identity and the public API

`MediaMeshSecurityConfiguration` installs Spring's JWT resource server. It
validates signatures through the provider's JWKS and checks issuer, audience,
and token timestamps. `IdentityService` maps `(issuer,subject)` to an internal
UUID, then reads roles from `user_roles` for each request. We ignore token role
claims so a revoked role takes effect with the same still-valid JWT.

First sign-in creates a user with no roles. Only a configured bootstrap
subject receives ADMIN once. Admin changes replace the full role set inside
a transaction and append an audit event. A database transaction lock protects
the rule that the final administrator cannot be removed.

API sessions are keyed by the provider's `sid`. The server enforces a
30-minute idle limit, an 8-hour absolute limit, and explicit logout revocation.
Keycloak enforces corresponding provider limits. Browser tokens stay in memory;
there are no custom passwords or JWT issuers in the application. The React
activity timer logs idle users out even while status polling is active.

`CatalogController` implements metadata/list/edit/access routes. Owners with
UPLOADER can manage their own assets. Researchers can read READY assets.
Only a researcher gets a 60-second GET URL, and issuance is audited. Roles can
be combined; ADMIN alone does not permit uploading or searching.

`SearchController` asks PostgreSQL for IDs satisfying READY and metadata
filters, passes that set to Python, and enriches ranked IDs back into metadata.
Filtering before ranking avoids dropping valid matches outside an arbitrary
unfiltered candidate list. The browser never calls internal Python endpoints.

Verification uses PostgreSQL containers, generated RSA signing keys, and a
local JWKS server. Tests cover 401/403, audience/expiry checks, role revocation,
session expiry/logout, ownership, and READY-only access.

## Checkpoint 3: make uploads become searchable

Upload initiation generates a UUID/key and signs a PUT with a content type and
`If-None-Match: *`. That condition prevents reusing the URL to overwrite an
indexed source. Completion checks object length and media category. It locks
the asset row, creates one job, and switches UPLOADING to PROCESSING in the
same transaction. Duplicate completion returns the existing state; a failed
job insert rolls back the state transition.

`PostgresJobStore` reuses the existing lease/retry logic with production tables.
Its local adapter preserves the original standalone demos. `SKIP LOCKED`
lets workers claim distinct jobs without waiting on one another. A unique
claim token and lease expiry fence stale workers: an old process cannot
publish results after a job has been recovered by another worker.

`S3MediaSource` downloads the exact private key into a temporary file, enforces
size limits while streaming, and deletes temporary bytes on success or error.
The existing image/video pipeline decodes the file, samples timestamped video
frames, and generates normalized 512-dimensional CLIP embeddings.

Completion checks the claim and writes vectors, job SUCCEEDED, and asset READY
in one DB transaction. A crash cannot expose READY metadata without vectors.
Failures use bounded backoff; exhausted/non-retryable work marks the asset FAILED.
Related media uses an image vector or the first sampled frame for video.

The Python suite checks exclusive claims, stale fencing, recovery, rollback,
S3 download cleanup, vector scope, filtered ranking, and real FFmpeg sampling.

## Checkpoint 4: build the editorial workflow

React initializes Keycloak's adapter with Authorization Code + PKCE S256.
The API helper refreshes tokens before requests and redirects expired API
sessions through provider logout. `/api/me` controls visible navigation;
server checks remain the source of truth.

Upload uses XMLHttpRequest so the browser can display progress while sending
bytes directly to S3. The UI completes the upload and polls owned catalog
records for READY/FAILED. Editors can change metadata without reuploading.
Researchers submit natural language plus filters, see ranked results and
video offsets, open a signed preview, or download after reviewing rights notes.
The admin screen edits each account's role set.

Nginx serves the built portal and proxies `/api` to Spring and `/auth` to
Keycloak. PostgreSQL, Python, and the identity provider are not published as
separate host ports. S3 has a localhost port for direct signed transfers.
Persistent volumes keep the catalog, identities, objects, and model cache.

Playwright signs in through actual Keycloak pages, grants roles through the
portal, uploads an image, edits metadata, waits for indexing, searches,
previews/downloads, indexes a video, checks timestamps and related results,
and revokes access using an unchanged JWT. It uses synthetic fixtures and
real CLIP inference; wildlife retrieval quality is covered separately by the
existing ML evaluation assets/baselines.

## Checkpoint 5: make it repeatable

`infra/start.sh` builds and starts the integrated stack. `infra/check.sh`
runs Java tests, the frontend test/build, Python lint, and Python tests in an
FFmpeg-enabled container with isolated test databases. GitHub Actions repeats
these steps and adds the browser acceptance run. Jenkins has a simpler check/
container-build pipeline for the course environment.

The checked-in demo credentials are deliberately local fixtures. Cloud deployment
uses Azure managed identity and private Blob Storage, with no cloud access keys.
Azurite exercises the Blob API locally; real Azure IAM/CORS and public HTTPS
still require validation against the configured cloud account.

This remains the agreed MVP: exact vector ranking and small-catalog queries,
a single internal pilot library, advisory rights notes, and no custom queue
or distributed-storage system. Large archives need indexed filtered ranking
and a separately sized deployment.

## Azure student deployment checkpoint

The cloud deployment target is now Azure VM + private Blob Storage. `MediaStorage`
is the backend boundary; the Azure adapter signs narrow SAS using managed
identity. The same adapter uses Azurite for local development; AWS SDKs and
the S3 adapter have been removed. Upload
responses now include optional storage headers, so React can send BlockBlob
without guessing the provider from the URL. Python uses `AzureBlobMediaSource`
for the production worker and preserves size limits, temporary-file cleanup and the
existing indexing/job/search flow. ETag checks avoid indexing a changed version
during a download. The database's historical `s3_key` name remains unchanged.

The deployment generator creates fresh OIDC identities and Azure account/container
configuration, with no Azure keys. Compose keeps PostgreSQL, Keycloak, ML and
metrics internal, and Caddy supplies HTTPS. Local adapter tests and configuration
checks guide the implementation; real managed identity, SAS/CORS and uploaded
media must still be verified on Azure. See `infra/deploy/README.md` for resources,
student-credit controls, launch, backup and recovery steps.
