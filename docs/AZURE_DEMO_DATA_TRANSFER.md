# Demo collection transfer to Azure

> **Retired.** This records a one-off import that used password-based demo
> accounts, which the Google-only application no longer accepts; its
> `accounts.json` fixture and provisioning script are gone. To load the demo
> collection now, sign in as the administrator and use the **Seed** tab (see
> [the demo dataset guide](../infra/demo/README.md)).

This transfers the curated **48 photos and 2 videos** from the working local
demo into the deployed application. It uses the normal upload/completion APIs,
private Blob SAS and the real cloud ML worker. It does not restore the localhost
database or import localhost passwords, sessions, administrators or vectors.

## Checkpoint 1 — inventory and recovery point

The target is subscription `bf5064f9…`, resource group
`CMPE-272-Media-Mesh`, VM `vm-media-mesh-demo`, and private container `mediamesh`
in account `mm272bf5064f9demo`. The public origin is
`https://mediamesh-demo-bf5064f9.swedencentral.cloudapp.azure.com`.

Before import, the cloud asset catalog was empty. Existing administrator and
user roles were left in place. `infra/deploy/backup.sh` created the pre-import
database dumps in `backups/20261126T231822Z/` on the VM. Configuration and identity
databases are private; never commit or publicly upload these backups.

The source is `ml-service/evaluation/demo-manifest.json`; files are in ignored
`ml-service/data/demo/`. All 50 SHA-256 values were checked before any upload:
**13,377,219 bytes**. Credits, licenses and source links are required. The local
catalog, Azurite volume and source files remain available as recovery copies.

## Checkpoint 2 — separate cloud identities

`infra/deploy/provision-demo.py` runs on the VM via SSH. It reads private runtime
configuration and uses the internal Keycloak administrator API to create only
the seven named demo identities. Each gets a unique random password in private
`infra/deploy/runtime/demo-accounts.json`. It never uses `local-demo-only`.

| Cloud username | Role | Collection |
|---|---|---|
| demo.wildlife | UPLOADER | 8 photos, 2 videos |
| demo.plants | UPLOADER | 8 photos |
| demo.oceans | UPLOADER | 8 photos |
| demo.marine | UPLOADER | 8 photos |
| demo.birds | UPLOADER | 8 photos |
| demo.landscapes | UPLOADER | 8 photos |
| demo.researcher | RESEARCHER | Searches the shared READY library |

The SSH operator provisions these accounts' application user/role rows in one
database transaction, with `DEPLOYMENT_DEMO_PROVISION` audit entries. This is an
explicit administrative bootstrap, not the browser Admin API. No ADMIN role is
granted, existing human roles are not modified, and existing identity collisions
or unexpected roles stop provisioning. Existing demo passwords are not reset on
reruns. Their names/emails are fictional demo identities, not real employees.
The production administrator's password and MFA setup remain independent.

On the VM, from `/opt/mediamesh`:

```bash
sudo ./infra/deploy/backup.sh
python3 infra/deploy/provision-demo.py \
  --expect-domain mediamesh-demo-bf5064f9.swedencentral.cloudapp.azure.com
```

Copy `infra/demo/accounts.json` and the provisioning script to the VM first.
Transfer `runtime/demo-accounts.json` back over verified SSH into a private
directory outside the repository, with directory permissions 700/file 600.
Never paste it into a terminal transcript or send it as a public attachment.

## Checkpoint 3 — authenticated uploads and new indexing

Run on the local workstation with Docker/source files available, Node 24 and
the frontend Playwright dependencies/browser installed:

```bash
cd frontend
node scripts/import-cloud-demo.mjs \
  "$HOME/.local/share/mediamesh/azure-deployment/demo-accounts.json" \
  https://mediamesh-demo-bf5064f9.swedencentral.cloudapp.azure.com
```

The target origin must exactly match the private account file and use HTTPS.
The importer checks every source checksum, signs in each account using OIDC
Authorization Code + PKCE, and checks its application identity and exact roles.
Passwords/tokens/SAS URLs are not printed.

For each item it:

1. Calls `POST /api/assets/initiate` as the domain uploader, with description,
   species, location, capture date and original credit/license/source notes.
2. Uses a real browser `fetch` to PUT bytes to the create-only Azure SAS with
   `x-ms-blob-type: BlockBlob`, Content-Type and `If-None-Match: *`. This exercises
   browser CORS, not just a server-side HTTP upload.
3. Calls `POST /api/assets/{id}/complete`. The backend verifies size/type and
   atomically creates the indexing job; the cloud worker downloads via managed
   identity, decodes media and creates fresh CLIP vectors in pgvector.
4. Polls until all 50 assets are READY. Any FAILED asset stops the import.

Cloud asset/user UUIDs and object keys are new. Ownership is preserved by domain
account, not by copying localhost IDs. Fresh embedding generation verifies the
actual Azure worker path; localhost vectors are intentionally not copied.

Progress is private `demo-upload-state.json` beside the credential file. Reruns
reuse saved IDs and can recover an upload that reached storage but not completion.
Existing title/source matches protect against duplicates if the state file is
lost. A crash between initiation and the actual PUT requires operator review:
the script will not overwrite a blob or silently create replacement assets. An
expired upload URL cannot be renewed with the current API; do not reset a whole
catalog to repair one incomplete item. Keep the state file for scoped recovery.

## Checkpoint 4 — evidence and handoff

Run the read-only acceptance script from `frontend/` after import:

```bash
node scripts/verify-cloud-demo.mjs \
  "$HOME/.local/share/mediamesh/azure-deployment/demo-accounts.json" \
  https://mediamesh-demo-bf5064f9.swedencentral.cloudapp.azure.com
```

It writes private `demo-transfer-report.json` beside the credential/state files.
The report has counts and search observations, with no passwords, tokens or SAS.
Client-observed query times include network latency; they are not the API-boundary
SLI. Live SLO counters are in Prometheus, reached by SSH tunnel as documented in
the deployment runbook.


Verify source/destination SHA-256 hashes for every imported object, 50 READY
assets, successful jobs and vectors. Sign in as each uploader and confirm its
domain assets. Sign in as `demo.researcher`, search all six domains and check
inline gallery photos, preview dialogs and downloads. Verify an uploader cannot
read another uploader's private catalog row or invoke semantic search.

After validation, create another database backup and copy backups/private account
configuration off-host securely. Record results below. The accounts are intended
only for this course demo: share credentials privately, rotate them after sharing,
disable them after the presentation, and retain no public default password.

This remains a single burstable VM. Initial inference or search during indexing
may exceed the 1.5-second dependency deadline; failures still consume error budget.
A successful demo is not proof of meeting a rolling 30-day SLO.

## Recovery

An import failure does not affect the localhost source. Stop the importer first
and inspect its saved IDs and worker logs. Do not run `down -v` or restore an old
identity database over a live realm. Whole-database restore would also roll back
human account changes made since the snapshot, so it needs a deliberate recovery
window and the deployment runbook. Prefer fixing a specific pending item over
deleting the collection. Revoke/disable only the seven demo identities if their
credentials are exposed; existing humans and administrators are separate.

## Execution results

Completed on **2026-11-26 (UTC)**:

- All **50 assets READY**: 48 images and 2 videos; 50 indexing jobs SUCCEEDED.
- **64 vectors across all 50 assets**, freshly produced by the cloud worker.
- All **50 downloaded Blob SHA-256 values match** their source manifests.
- Seven cloud SSO accounts have exactly their intended roles. Provisioning was
  rerun successfully: seven provisioning audit entries remain, without duplicate
  accounts/password resets. The existing ADMIN count remains one.
- Each domain uploader owns only its expected collection: wildlife 10; plants,
  oceans, marine, birds and landscapes 8 each. Cross-owner access and uploader
  semantic search are denied.
- Six authenticated semantic queries returned results. Elephant, sunflower,
  ocean waves, sea turtle and puffin queries ranked the intended subject first.
  **Known ranking limitation:** “mountain lake” ranked the Palawan mangrove coast
  first. CLIP similarity is approximate and this is not an exact text lookup.
- Client-observed API search times were **229–297 ms** for those six calls.
  This is one small demo sample, not a 30-day availability evaluation.
- Browser inline photo, preview dialog and attachment download checks passed.
  Uploaded videos were decoded/indexed and their full bytes checksum-verified;
  this run did not separately assert in-browser video playback.
- Prometheus observed seven valid searches after browser acceptance. An intentional
  forbidden uploader search was excluded from this denominator.
- Post-transfer database dumps are in `backups/20261126T232408Z/` on the VM.
  Pre/post dumps were also copied over verified SSH to private local
  `~/.local/share/mediamesh/azure-deployment/demo-transfer-database-backups.tar.gz`.
- Mismatched-origin import was rejected before browser/login/upload. Existing
  deployment configuration tests, Python compilation and JS syntax checks pass.

The full private verification report and per-item cloud IDs are in
`~/.local/share/mediamesh/azure-deployment/demo-transfer-report.json` and
`demo-upload-state.json`. Copies also reside in the VM's private runtime folder.
**2026-11-26 update:** all seven demo logins are now **disabled** in Keycloak and
their API sessions revoked; `demo-logins.txt` no longer works. Their uploaded
media stays in the library. New researchers and uploaders are created by the
administrator in the Admin page (temporary password, then password change and
authenticator setup). Do not rerun `provision-demo.py`.

