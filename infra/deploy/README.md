# Azure student deployment: one VM + private Blob Storage

The current cloud target is Azure. `compose.deploy.yaml` is a standalone project
with fresh volumes, HTTPS via Caddy, production-mode Keycloak, PostgreSQL/pgvector,
Spring Boot, React, the Python API/worker and Prometheus. Only HTTP/HTTPS are
public; Prometheus binds to loopback. Cloud storage uses the VM's system-assigned
managed identity and user-delegation SAS. No storage account key, client secret,
or downloaded service-account credential is required.

The localhost stack uses Azurite Blob Storage and its migrated 50-item collection.
Do not merge the deployment file with `compose.yaml`, reuse the localhost realm,
or change the provider on a populated catalog: existing object bytes are not
migrated automatically. Historical `s3_key` column names remain to avoid an
unrelated schema migration; cloud object keys still begin with `assets/`.

## 1. Create only these Azure resources

Use one resource group, for example `rg-mediamesh-demo`, in a region permitted by
your student subscription:

- One Ubuntu 24.04 **x64** VM. The student demo currently uses
  `Standard_B2as_v2` (2 vCPU / 8 GiB) in Sweden Central, with no GPU. Build
  sequentially and validate inference latency under actual load. Larger memory
  and CPU sizes are an option if measurements justify their additional cost.
- A 64–100 GiB Standard SSD OS disk. Docker images, two CLIP processes, the model
  cache, database and metrics need more memory/disk than a tiny web application.
- A VNet/subnet, NIC, public IP and network security group created with the VM.
  Allow TCP 80/443 publicly; restrict SSH to your own IP. Do not expose database,
  ML, backend, Keycloak administration or Prometheus ports.
- Enable the VM's **system-assigned managed identity**. Save its principal ID.
- One **StorageV2 / Standard / LRS** storage account in the same region. Require
  HTTPS/TLS 1.2+, disable anonymous blob access and shared-key access, and create
  a **private container** named `mediamesh`. Keep the Blob public network endpoint
  reachable for browser SAS uploads/previews; a private container is still
  authenticated and does not allow anonymous reads. A VM-only network firewall
  would also block remote browsers despite their valid SAS.
- A public DNS hostname pointing to the VM's public IP. Caddy needs inbound
  80/443 and working DNS to issue a trusted certificate.
  You can use the Azure public IP's DNS name label (`*.cloudapp.azure.com`)
  rather than buying a domain; use the full hostname shown by the portal.

Do not add AKS, an Azure-managed database, GPU, load balancer or container registry
for this course demo. PostgreSQL and Keycloak stay on the VM. One host is a
failure domain; this is not a highly available enterprise deployment.

### Protect the $100 credit

Set a Cost Management budget/alerts and VM auto-shutdown. Budget alerts do not
stop spending. When idle, verify **Stopped (deallocated)** in the Azure portal;
shutting down only inside Linux can leave compute billable. Disks, storage and
some networking can still incur charges while compute is deallocated. Review
remaining credit and pricing before a presentation; no fixed demo lifetime or
monthly price is promised. Do not remove the student spending limit casually.
Delete this dedicated resource group after the course only when its data and
backups are no longer needed.

## 2. Assign storage permissions without keys

In Azure IAM, assign the VM's managed identity:

1. **Storage Blob Data Contributor** on the specific `mediamesh` container.
2. **Storage Blob Delegator** on the storage account, to request delegation keys.

Contributor is a built-in role that also permits deletion; a custom read/write
role can narrow that later. Do not assign Owner/Contributor at subscription scope
for application access. The two application processes share the VM identity
trust boundary; this is not a separate identity per Docker container. Role
assignments can take time to propagate. Creating these assignments requires
Owner, User Access Administrator, Role Based Access Control Administrator, or
an appropriately scoped access-management role. The ordinary Contributor role
can create storage resources but cannot grant these permissions. If Azure
returns `AuthorizationFailed` for `Microsoft.Authorization/roleAssignments/write`,
ask the subscription access administrator to assign the roles; do not enable
shared keys as a workaround. No Microsoft Entra enterprise SSO change
is required: MediaMesh employee login continues to use Keycloak OIDC/RBAC.

In the storage account's **Resource sharing (CORS)** section, configure Blob:

- Allowed origins: exactly `https://YOUR_HOSTNAME`.
- Allowed methods: GET, HEAD, PUT, OPTIONS.
- Allowed headers: content-type, if-none-match, x-ms-blob-type, x-ms-version, range.
- Exposed headers: ETag; cache age: 300 seconds.

Enable blob versioning/soft delete with a short, deliberate retention policy
within your credit budget. Anonymous container access remains disabled.

## 3. Generate private runtime configuration on the VM

Install Docker Engine/Compose v2, Git and Python 3 on Ubuntu. Check out the
reviewed release. The local workspace has many uncommitted implementation files;
review and commit only intended source/config/tests before deployment. Verify the
remote: local `origin` currently points to `sagarparker/CMPE_272_PROJECT`, whereas
the supplied project is `mathewpius19/Media-Mesh`. Do not push to the wrong repo.

```bash
python3 infra/deploy/prepare.py \
  --domain archive.your-domain.org \
  --email operations@your-domain.org \
  --admin-email you@example.com \
  --account YOURLOWERCASESTORAGEACCOUNT \
  --container mediamesh
# Before starting, add ML_OPENROUTER_API_KEY to the private runtime/deploy.env.
# Keep the key out of source control and do not print resolved Compose config.
./infra/deploy/compose.sh config --quiet
./infra/deploy/compose.sh up -d --build
./infra/deploy/compose.sh ps
./infra/deploy/compose.sh logs -f ml-api ml-worker keycloak edge
```

Replace every example first; account names use 3–24 lowercase letters/digits.
Preparation creates ignored `infra/deploy/runtime/` with private database/admin
credentials, a fresh realm and `azure-cors.json` as a CORS reference. It does not
create paid Azure resources or assign roles. It refuses to overwrite existing
identities. Never paste `compose config` output without `--quiet`: it resolves
private credentials. Keep runtime files private and securely back them up.

First start downloads the pinned CLIP model. Azure ManagedIdentityCredential
requests temporary tokens from the VM metadata service; the Python worker uses
Azure Blob SDK downloads and Java generates HTTPS-only SAS. The delegation key
is cached briefly; every preview SAS still lasts only 60 seconds. Upload SAS is
create-only for 15 minutes and the client sends BlockBlob + If-None-Match headers.
The API checks size/content type and the worker checks decoding/video duration.
The signed PUT does not itself enforce the 100 MB application limit before bytes
are stored. A local stub/unit test is not proof that Azure IAM/SAS/CORS works.
First inference and concurrent builds can exceed the 1.5-second ML deadline even
after model loading. Validate startup and load behavior on the chosen VM; the
two-second search SLO is measured, not guaranteed by the VM size or readiness.

## 4. Verify the deployed application

```bash
curl --fail --connect-timeout 3 --max-time 10 https://YOUR_HOSTNAME/health
curl --fail --connect-timeout 3 --max-time 10 https://YOUR_HOSTNAME/auth/realms/mediamesh/.well-known/openid-configuration
./infra/deploy/compose.sh exec -T ml-api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/ready',timeout=3).read().decode())"
```

Discovery must advertise exactly your HTTPS issuer. Anonymous `/api/me` returns
401; `/actuator/prometheus` and `/auth/admin/` return 404 publicly. Read the initial
Google sign-in configuration from [account setup](../../docs/ACCOUNT_SETUP.md).
Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `runtime/deploy.env`, register
the hosted broker redirect URI, and sign in as the Google email configured by `ADMIN_EMAIL`. The
application creates its sole administrator from that verified Google login.
There is no temporary application password or additional administrator creation.

Keycloak identity administration remains internal. Authenticate its CLI (password
prompt; use the generated private management password):

```bash
./infra/deploy/compose.sh exec keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080/auth --realm master --user deployment-admin
```

Application access now follows the Google request/approval flow. Only
the Google email configured by `ADMIN_EMAIL` receives ADMIN. See [account setup](../../docs/ACCOUNT_SETUP.md)
for existing-realm migration and role approval.

The backend deletes retired sign-in identities through the `mediamesh-provisioner` client, whose
service account holds only `realm-management/manage-users` and the
`kc-admin-api` scope that Keycloak 26.8.2+ requires for Admin API tokens.
`prepare.py` adds it to fresh realms. For a realm created before this change,
run once on the VM, then rebuild:

```bash
python3 infra/deploy/add-provisioner.py --expect-domain YOUR_HOSTNAME
sudo ./infra/deploy/compose.sh up -d --build backend frontend
```

Video previews play a browser-safe copy (H.264/AAC MP4, standard range, upright,
at most 1080p/30 fps) that ml-worker writes to `assets/.../playback/web.mp4` after
indexing; downloads always return the original upload. Phone HEVC/HDR/Dolby Vision
originals otherwise render incorrectly in many browsers. A 10-second 4K60 iPhone
clip takes about a minute on this VM. For videos indexed before this feature, run:

```bash
sudo ./infra/deploy/compose.sh exec -T ml-worker python -m mediamesh_ml.playback backfill
```

Replace the temporary management administrator with a named MFA-protected
administrator, rotate credentials and remove the bootstrap password from the
environment after setup.

From a browser outside Azure: upload a JPEG and a short MP4, wait for READY,
search as researcher, see gallery photos, preview/download and revoke access.
Verify upload URLs use `blob.core.windows.net`, have create-only SAS, send
`x-ms-blob-type: BlockBlob`, and cannot overwrite an existing blob. Read SAS must
not allow writes; anonymous object access must fail. Verify real managed-identity
worker reads, not just the backend's signing ability. Do not claim Azure is live
until these checks pass. The localhost dataset is not automatically transferred.

## 5. Checks, monitoring and recovery

Before release:

```bash
./infra/check.sh
./infra/security-check.sh
python3 infra/deploy/smoke-test.py
# With localhost services/model ready:
(cd frontend && npm run test:e2e)
```

The opt-in deployment smoke test creates temporary PostgreSQL/Keycloak containers,
validates the fresh realm, HTTPS issuer, password/MFA actions and database dump/
restore, then removes only its own volumes. It does not test real Azure identity,
Blob SAS, public DNS or trusted certificate issuance. Security scanning includes
source and packaged backend/frontend; scan/review remaining infrastructure images
and non-KEV advisories before public exposure. Retain the reviewed Git commit and
image digests as the release record; no automatic CD is configured.

Tunnel Prometheus rather than opening it publicly:

```bash
ssh -L 9091:127.0.0.1:9091 YOUR_USER@YOUR_VM_IP
```

Open localhost:9091 and check backend UP, actual search SLIs, latency, budget and
burn-rate rules. Metrics retain 35 days but a new deployment has partial history.
Prometheus firing alerts do not send real notifications without a receiver.
See the [SLO runbook](../../docs/observability/SLO_ERROR_BUDGET.md).

Run `./infra/deploy/backup.sh` regularly. Encrypt/copy both database dumps and
private runtime configuration off-host. Blob version history is separate from
database consistency. Before upgrades, retain VM/disk recovery points and the
last known-good release/images. Test recovery into an isolated VM with matching
identity/issuer and storage objects; keep the edge closed until acceptance passes.
With PostgreSQL running and all application/identity writers stopped:

```bash
./infra/deploy/compose.sh stop edge frontend backend ml-api ml-worker keycloak prometheus
cat backups/TIMESTAMP/mediamesh.dump | ./infra/deploy/compose.sh exec -T postgres pg_restore -U mediamesh -d mediamesh --clean --if-exists --exit-on-error
cat backups/TIMESTAMP/keycloak.dump | ./infra/deploy/compose.sh exec -T postgres pg_restore -U mediamesh -d keycloak --clean --if-exists --exit-on-error
./infra/deploy/compose.sh up -d
```

Restore overwrites the target databases; preserve newer data first and use only
your chosen recovery environment. Verify identities, owner mappings, roles,
READY assets, Blob objects and search before reopening access. Flyway does not
reverse migrations automatically: incompatible rollback needs matching backups.
Never run `down -v` against a live deployment project.

References: [Student credit terms](https://learn.microsoft.com/azure/education-hub/about-azure-for-students),
[VM billing states](https://learn.microsoft.com/azure/virtual-machines/states-billing),
[budget alerts](https://learn.microsoft.com/azure/cost-management/tutorial-acm-create-budgets),
[Java user-delegation SAS](https://learn.microsoft.com/azure/storage/blobs/storage-blob-user-delegation-sas-create-java),
[Python managed identity](https://learn.microsoft.com/azure/developer/python/sdk/authentication-azure-hosted-apps).

For the curated collection, sign in as `ADMIN_EMAIL` and use the **Seed** tab; see
[the demo dataset guide](../demo/README.md). It writes to this deployment's Blob
container with the VM managed identity and needs outbound HTTPS to Wikimedia. Run
`sudo ./infra/deploy/backup.sh` first.


## Search parity with the integrated stack

This standalone manifest still defaults to CLIP, with separate model instances
in the API and worker. OpenRouter caption settings are available for new uploads,
but `gemma-embed`, `ML_EMBEDDING_MODEL=embeddinggemma2` and hybrid verification are
not wired in here. The default backend ML deadline is also 1.5 seconds. The root
stack's 80/20 hybrid search and hosted final check must not be assumed on Azure.

Before deploying the current local search behavior, add the shared embedding
service and matching model configuration, enable verification, align deadlines,
reindex the deployed catalog with the new embedding version, refresh metadata
vectors and validate search/caption/Blob access against the real host. Do not mix
CLIP vectors with Gemma query vectors. Credentials belong in private
`runtime/deploy.env`; copy neither root `.env` nor demo credentials into source.
See the [current Mermaid diagrams](../../README.md#system-architecture) and
[architecture guide](../../docs/architecture/README.md). This documentation change
does not claim those infrastructure/migration steps have been performed.
