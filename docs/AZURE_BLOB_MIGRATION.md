# Azure Blob Storage migration

MediaMesh now uses Azure Blob SDKs in Java and Python for all application media
storage. The AWS Java SDK, boto3, S3 adapter and S3 Compose override were removed.
Cloud deployment uses system-assigned managed identity, HTTPS-only user-delegation
SAS, create-only upload access, and 60-second read-only previews/downloads.

## Checkpoint 1: one storage contract

The backend's `MediaStorage` interface covers upload signing, access signing and
upload verification. `AzureBlobStorage` implements it for both Azure and local
Azurite. An optional `uploadHeaders` map tells React to send
`x-ms-blob-type: BlockBlob`. Clients retain `If-None-Match: *`; create-only SAS
also prevents overwrite when that header is omitted. Completion verifies size
and media type, and the existing worker validates image/video decoding limits.

The database's historical `assets.s3_key` column still holds opaque object keys
such as `assets/<owner>/<asset>/source/photo.jpg`. Java calls these `objectKey`;
the column name remains for compatibility, with no changes to IDs, ownership,
metadata, job state or vector references. It does not imply an S3 dependency.

## Checkpoint 2: Azure locally as well as in deployment

Default `compose.yaml` uses Azurite on **localhost:10000**. `blob-init` creates the
private container and browser CORS before Spring starts. Java and Python use
Microsoft's public `devstoreaccount1` fixture, restricted in code to explicit
local HTTP emulator endpoints. No actual Azure account key can be supplied.
These credentials provide no protection and must never be used with real data
on a public endpoint. The local Blob port is bound to loopback.

The standalone `compose.deploy.yaml` contains neither emulator endpoints nor
account keys. Java obtains a delegation key using managed identity and caches it
with a refresh margin; Python obtains managed-identity tokens for reads.
Azurite uses shared-key SAS for local tests, so it cannot prove real Azure
managed-identity role assignments, user-delegation behavior or cloud CORS.

## Checkpoint 3: preserve existing local media

For this workspace, **69 objects / 13,405,349 bytes** were exported from the old
S3 emulator to ignored `ml-service/data/s3-migration-backup/`. Its manifest
records exact keys, sizes, content types and SHA-256 hashes. Every object was
copied into Azurite and downloaded again to verify its checksum. Original
objects and the old `mediamesh_s3-data` volume were retained as recovery copies.
The database was not reset and existing vectors remain valid for identical bytes.

On another older checkout, perform the same process before changing its running
backend/worker: pause uploads, export source objects, copy the same keys/content
types to the private Blob container, verify downloaded hashes, and only then
switch the application. Never point an existing database at an empty container.
The committed application deliberately has no general S3 migration dependency;
an export from legacy storage is a separate one-time administrative operation.
Do not delete recovery copies until catalog access and backups have been verified.

## Validation

Run `./infra/check.sh` and the browser suite after the model is ready. Browser
acceptance verifies photo/video upload, duplicate/overwrite rejection, completion,
indexing, search, gallery previews, downloads, related media, and role revocation.
`./infra/seed-demo.sh` reuses the existing collection; its guard now requires local
Azurite and public local Keycloak fixtures. It cannot seed the cloud deployment.

Verified in this workspace: 36 Java tests, 4 frontend unit tests, 105 Python
tests, deployment configuration tests, Prometheus configuration/rule tests, and
5 browser tests passed. Six Python model opt-in tests and two explicit browser
outage/load demonstrations were skipped. The security gate reported no CISA KEV
intersection or secret findings; this does not mean there are no advisories.
The demo verifier found all 50 assets READY, verified each domain uploader
ownership, searched all six domains, and rendered an existing Blob preview.
The old S3 emulator was stopped after validation; its volume and export remain.

Azure account/container setup and role assignments remain described in the
[deployment runbook](../infra/deploy/README.md). The VM being provisioned is not
evidence that its real Blob storage integration has been exercised.
