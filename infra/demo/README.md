# Nature showcase dataset

The manifest contains 500 photographs across six nature domains, plus two legacy
wildlife videos. The seed command now selects **images only**, owned by the sole
Google administrator. It creates no dummy users or password-based logins.

## Seed tab (local and deployed)

Sign in with Google as `ADMIN_EMAIL` and open the **Seed** tab. Choose 20, 50,
100 or 500 images and select **Load**. The backend downloads the checksum-pinned
images from Wikimedia, writes them to the storage it is configured with (Azurite
locally, the Azure Blob container in deployment), and queues normal indexing jobs.
The images are owned by your administrator account. The tab shows how many
are stored, indexing and ready, and updates every few seconds; you can leave the
page while it runs.

One run happens at a time. Starting again resumes an interrupted run and skips
images already in the library, including ones added by `./infra/seed-demo.sh`,
because both use the same asset IDs. Images that failed indexing are counted but
not retried; check the ML worker logs. Captions use OpenRouter credit when
`ML_CAPTION_ENABLED` is on. In deployment, the VM needs outbound HTTPS to
Wikimedia, and its managed identity already has the required **Storage Blob
Data Contributor** role on the container. To browse the images in Search,
enable the Researcher role for yourself on the Admin tab.

The backend bundles `ml-service/evaluation/demo-manifest.json` at build time
(Maven resource plus the `evaluation` Docker build context), so rebuild the
backend after changing the manifest.

## Command-line seed (local only, no sign-in)

Set `ADMIN_EMAIL` to your Google email in the root `.env`, alongside the existing
Google OAuth credentials and `ML_OPENROUTER_API_KEY`. You do not need to sign in
before seeding. On a fresh catalog the seed reserves the administrator account for
`ADMIN_EMAIL` and owns the images with it; your first Google sign-in as that email
claims the reserved account, including its images and ADMIN role. If the email
already has an account, or a different administrator is registered, the seed stops
and asks you to sign in first so the backend handles the handover. To browse
Contributions or Search, grant your own account Uploader/Researcher roles from
Admin; ADMIN does not implicitly include those roles. Rebuild the backend if
changing `ADMIN_EMAIL` on an existing stack.

With Docker running and Node.js 22+ (24 LTS recommended):

```bash
./infra/seed-demo.sh       # 20 images by default
./infra/seed-demo.sh 20
./infra/seed-demo.sh 50
./infra/seed-demo.sh 100
./infra/seed-demo.sh 500
```

Change `DEFAULT_IMAGES` inside `infra/seed-demo.sh` to change the default. Other
counts fail before any stack operations. The script builds/starts the stack,
validates the hosted caption model, downloads only the selected checksum-pinned
images, uploads to Azurite and queues normal indexing jobs. Local operator
provisioning writes the catalog directly; app sign-in continues to require
verified Google authentication. No browser or frontend dependency installation
is needed for seeding.

To rerun against an already built/running stack:

```bash
npm --prefix frontend run seed:demo -- --images 50
```

The deterministic subsets cover all six domains and are nested: increasing from
20 to 50 reuses the first 20 images. Reruns reuse existing assets and resume
interrupted uploads. Selecting a smaller count does not delete images from a
previous larger run or unrelated uploads. FAILED jobs stop the run for inspection.
The worker gets up to two hours to finish; missing captions/current embeddings
are then backfilled only for the selected IDs. The final counts and asset IDs
are saved in ignored `ml-service/data/demo/seed-report.json`.

## Legacy dummy users

Fresh realm imports contain only the Keycloak provisioner service account.
`accounts.json` is kept only to identify old local demo logins for cleanup. On
an existing local stack the seed removes those seven dummy logins and the old
`admin`, `uploader`, `researcher`, and `employee` password logins. It transfers
their existing uploads to the configured administrator, revokes application
roles/sessions, and hides their application records while preserving audit history.
A changed email or Google-linked legacy identity stops cleanup for inspection.
Real Google users and the Keycloak administrative/service accounts are preserved.
The old cloud dummy-account provisioning command is retired.

## Sources and limits

[`demo-manifest.json`](../../ml-service/evaluation/demo-manifest.json) records
creator, source, license, domain and SHA-256. Image bytes stay in ignored
`ml-service/data/demo/`. See the [attribution guide](../../ml-service/evaluation/DEMO_ATTRIBUTION.md).
Retain credits and applicable license terms, including CC BY-SA requirements.

Seeding is restricted to the local development Compose database and Azurite.
Caption generation consumes OpenRouter credit; image and metadata embeddings
stay local. Source URLs can disappear or change; checksum failures require
reviewing the replacement and its rights. Keep Compose volumes to preserve
users, media and indexing state.
