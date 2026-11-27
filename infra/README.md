# Integrated development and acceptance runbook

## Start

Install Docker Desktop/Compose. Allocate at least 8 GB of Docker memory and
allow several GB for images/model cache. From the repository root:

```bash
./infra/start.sh
```

Open http://localhost:8080. First start needs network access for images and
the pinned Hugging Face CLIP model. Later starts reuse the `model-cache`
volume. Follow readiness with `docker compose logs -f ml-api ml-worker` or
`docker compose ps` (the ML API reports healthy only after model/schema load).

Keycloak imports the development realm and four local accounts. Password for
`admin`, `uploader`, `researcher`, and `employee`: `local-demo-only`. The
identity-provider management account is `local-admin` / `local-development-only`.
These fixtures are public and intended only for the localhost development stack.

1. Sign in once as uploader and researcher, then sign out.
2. Sign in as admin. Grant UPLOADER to uploader and RESEARCHER to researcher.
3. Upload JPEG/PNG or an MP4/QuickTime clip (up to 100 MB and 180 seconds).
4. Wait for READY, search, preview, and download as researcher.
5. Revoke the researcher role as admin; the next protected request is denied.

Use browser profiles for simultaneous accounts. A new employee has no roles.
An admin requires explicit uploader/researcher assignments for those actions.

## Verify

Host checks require Java 17+, Maven 3.9+, and Node 24+:

```bash
./infra/check.sh
```

This runs Java tests against isolated PostgreSQL containers, frontend checks,
and the complete Python suite inside an image with FFmpeg. The test database
is separate from the app database. Real-model benchmark tests require their
existing explicit opt-ins; browser acceptance below uses the real model.

With the application running and the ML API healthy:

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

Acceptance signs in through Keycloak, grants roles in the UI, uploads/edits
an image, indexes a video, checks search filters/timestamps, previews/downloads,
finds related media, and verifies revocation. It leaves synthetic test assets
in the catalog and restores uploader/researcher to unassigned roles.

GitHub Actions runs the checks and full browser acceptance. `Jenkinsfile`
provides the course Jenkins alternative for checks/container builds on an
agent with Java, Maven, Node, and Docker installed. CI has not been triggered
remotely until these files are committed and pushed.

## Azure Blob Storage

Local development uses Azurite on localhost:10000 with a private `mediamesh`
container. `blob-init` configures that container and browser CORS before Spring
starts. Java and Python both use the Azure Blob SDK; production uses managed
identity and the emulator uses Microsoft's public development-only credential.

For a real account on the Azure VM, use the standalone deployment described in
[the Azure runbook](deploy/README.md). It contains no emulator credentials or
endpoints. Existing local S3 media was copied and checksum-verified before the
switch; its old volume and an ignored export remain as recovery copies. See
[the migration notes](../docs/AZURE_BLOB_MIGRATION.md) before upgrading an older
checkout that still has objects only in S3.

## Stop and inspect

```bash
docker compose logs backend ml-api ml-worker
docker compose down
```

`down` preserves database, identity, storage, and model volumes. To delete all
local demo data deliberately, use `docker compose --profile test down -v`.
Never point destructive test fixtures at an application database. The original
standalone ML environment remains available under `ml-service/compose.yaml`.

The local stack uses Azurite; cloud deployment uses **Azure VM + Blob Storage**.
Use the [Azure deployment runbook](deploy/README.md) and standalone
`compose.deploy.yaml` rather than exposing the local fixtures publicly.
