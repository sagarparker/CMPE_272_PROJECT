# Deploy from your computer

Run `./deploy` from the project directory. It reads the local root `.env.deploy`, provisions
one new Azure Ubuntu VM and private Blob Storage, fetches your public GitHub repo,
and builds/starts the standalone Compose deployment. Later runs update the same
VM. No GitHub credentials or SCP are needed. No auto-shutdown schedule is created.

## 1. Install prerequisites

On macOS:

```sh
brew install azure-cli
```

Python 3, Git and SSH must also be available. Azure sign-in opens automatically
if needed when you run `./deploy`. Your Azure account must be able to create
resources and assign roles; ordinary Contributor cannot assign storage roles.

## 2. Fill in your local .env.deploy

If you don't already have `.env.deploy`:

```sh
cp .env.deploy.example .env.deploy
chmod 600 .env.deploy
```

The application keeps its separate `.env`. If `.env.deploy` exists, add the deployment settings from `.env.deploy.example` to it without
overwriting your existing values. Set:

| Variable | Value |
| --- | --- |
| `AZURE_SUBSCRIPTION` | Student subscription name or ID |
| `AZURE_RESOURCE_GROUP` | NEW resource group name |
| `AZURE_LOCATION` | Region permitted by your subscription, e.g. `swedencentral` |
| `AZURE_VM_NAME` | NEW VM name |
| `AZURE_DNS_LABEL` | Unique lowercase DNS label within that region |
| `AZURE_STORAGE_ACCOUNT` | Globally unique 3–24 lowercase letters/digits |
| `AZURE_STORAGE_CONTAINER` | Usually `mediamesh` |
| `ADMIN_EMAIL` | Administrator's verified Google email |
| `ACME_EMAIL` | HTTPS certificate contact email |
| `AZURE_SSH_KEY` | Dedicated local private key path; default `~/.ssh/mediamesh` |
| `AZURE_SSH_USER` | Default `azureuser` |
| `AZURE_VM_SIZE` | Default `Standard_B2as_v2` (2 vCPU / 8 GiB) |
| `GOOGLE_CLIENT_ID` | Google OAuth Web application client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `ML_OPENROUTER_API_KEY` | OpenRouter key for caption generation |

Settings and credentials are read from the file, without shell execution or
variable expansion. Quote values containing spaces. Use single-line credentials
without single quotes or backslashes. Errors identify missing variable names
without printing their values. The local file is ignored by Git. Never commit it.
Only the three application credentials are sent over SSH stdin to the VM's private
runtime configuration. Your Azure CLI credentials and private SSH key stay local.
Database/Keycloak passwords are generated on the VM and preserved across updates.
Credentials in `.env.deploy` are synchronized on every deployment; restart/status commands
don't require the three application credentials. Other local ML settings aren't
automatically copied to the cloud deployment.

To use a separate local file instead:

```sh
DEPLOY_ENV_FILE=.env.deploy.production ./deploy
```

## 3. Commit, push, and deploy

Deployments are restricted to `main`. Merge intended changes into `main` and push
before deploying. From the project directory:

```sh
git switch main
git pull --ff-only origin main
```

The checkout must be clean and local `main` must match published `origin/main`.
Feature branches and unpushed commits are refused before creating resources.

```sh
./deploy
```

The script validates settings, signs into Azure if necessary, and creates a
dedicated SSH key if absent (ssh-keygen may prompt for its passphrase). For a
passphrase-protected key, `ssh-add ~/.ssh/mediamesh` avoids repeated prompts.
It creates a NEW VM, 100 GiB Standard SSD, static public IP, DNS hostname, NSG,
managed identity, storage permissions, Blob CORS, versioning and seven-day soft
delete. Ports 80/443 serve the app and port 22 accepts SSH from any IP. The VM is
created with SSH key authentication; access requires an authorized private key.
It leaves your original VM and its services alone.

This creates billable resources. Check regional price, student quota and available
VM sizes first. No fixed lifetime for $100 credit is promised. There is no
automatic shutdown or budget setup: stop the VM yourself and set budget alerts in
Cost Management. Both old and new VMs consume credit if left running.

It installs Git/Docker on the VM, fetches the public `origin` repo over HTTPS,
checks out the exact commit, generates private runtime configuration, applies the
credentials from your local `.env.deploy`, builds sequentially, and starts the services.
The first build/model download can take a while. Azure IAM and SSH readiness may
need time to propagate; fix any reported error and rerun the same command.

Local state is saved in ignored `infra/deploy/runtime/azure-state.json`. Keep this
file, `.env.deploy` and your SSH key. Don't change resource names halfway through a
partially completed deployment. An existing resource group without matching local
state is refused to protect other resources.

## 4. Register Google login and test

The script prints your HTTPS hostname and this exact redirect URI:

```text
https://YOUR_HOSTNAME/auth/realms/mediamesh/broker/google/endpoint
```

Register it on your Google OAuth **Web application** client. Configure the consent
screen and test users if required. This step can be completed after the script
finishes, before signing in. Use the same Google credentials you put in `.env.deploy`.

Open the printed HTTPS URL, sign in as `ADMIN_EMAIL`, and test image/video upload,
indexing, search, preview and download. Health checks don't replace these tests.
The cloud profile still uses CLIP, not the local Gemma/hybrid search configuration.

## 5. Update and manage services

After merging changes into `main` and pushing, run `./deploy` again from `main`. Existing databases
are backed up before builds/migrations, and data volumes are preserved.

```sh
./deploy configure                # apply changed .env.deploy without rebuilding
./deploy logs backend ml-api      # recent logs; omit names for all services
./deploy status
./deploy restart backend
./deploy restart backend ml-api ml-worker
./deploy restart                  # all services
./deploy stop                     # stop containers; VM stays billed
./deploy vm-stop                  # deallocate the new VM
./deploy vm-start                 # start the new VM
```

Individual restart names: `edge`, `frontend`, `backend`, `postgres`, `keycloak`,
`ml-api`, `ml-worker`, `prometheus`. Restart does not apply code or environment
changes. After editing `.env.deploy`, run `./deploy configure` to synchronize
runtime settings and recreate affected containers without rebuilding. Normal
`./deploy` also applies the current administrator email. After changing ADMIN_EMAIL,
sign in with the corrected account; old administrator grants are removed by the
backend authentication flow. Google client changes are applied to the existing Keycloak realm automatically.
The script keeps a pending marker and retries failed provider updates on the next
deployment/configuration run. This requires the generated Keycloak management
credentials to remain valid; rotating them requires updating private runtime configuration. Containers running before VM deallocation should restart with Docker.
If you explicitly stopped containers, run `./deploy` after starting the VM.
Disk, public IP and Blob charges can continue while compute is deallocated.

For logs, SSH with your configured key/user to the printed hostname:

```sh
cd /opt/mediamesh/current
sudo ./infra/deploy/compose.sh logs --tail=100 backend ml-api ml-worker edge
```

Releases live under `/opt/mediamesh/releases/COMMIT_SHA`; `current` points to the
last successfully started release. Runtime secrets live in
`/opt/mediamesh/shared/runtime/deploy.env`. Existing database backups are placed in
the previous release's `backups/` directory. Securely copy/encrypt backups AND
runtime configuration off-host. No automatic off-host backup or release cleanup
is configured. Monitor disk usage.

Failed starts may already have applied database migrations: reverting the source
symlink alone isn't a transactional rollback. Don't run `down -v` or regenerate
runtime identities on an existing catalog. The script updates the Google provider on existing realms using the included
[account setup updater](../../docs/ACCOUNT_SETUP.md), because realm import is skipped
on restart. Azure infrastructure deletion is deliberately not provided.

Local tests cover configuration guards and Git release handling. The scripts have
not been validated against a live Azure deployment.

## Recovering or starting again

To correct ADMIN_EMAIL or application credentials, edit `.env.deploy` and run:

```sh
git switch main
git pull --ff-only origin main
./deploy configure
```

Sign out and sign in with the corrected Google account. The backend removes old
administrator grants during authentication. `restart` deliberately retains Docker's
normal restart behavior; use `configure` for env changes or `./deploy` for code changes.

You don't need a new VM or fresh database to correct settings. `./deploy` resumes
a partially completed installation using its existing state. It also starts
PostgreSQL before backup when application services were explicitly stopped.
Progress messages identify Azure operations and build stages. For failures, inspect
`./deploy logs` before rerunning. Do not delete local state or the Azure resource
group to retry. A fully independent new deployment needs its own checkout/state,
new resource names, and the corresponding Google redirect URI; it incurs new costs.
