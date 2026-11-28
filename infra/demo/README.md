# Nature showcase dataset

The manifest contains 500 photographs across six nature domains, plus two legacy
wildlife videos. The Seed tab loads **images only**, owned by the Google
administrator who starts it. It creates no dummy users or password-based logins.

## Seed tab (local and deployed)

Set `ADMIN_EMAIL` to your Google email (root `.env` locally, `runtime/deploy.env`
in deployment), sign in with Google as that account and open the **Seed** tab.
Choose 20, 50, 100 or 500 images and select **Load**. The backend downloads the
checksum-pinned images from Wikimedia, writes them to the storage it is configured
with (Azurite locally, the Azure Blob container in deployment), and queues normal
indexing jobs. The tab shows how many are stored, indexing and ready, and updates
every few seconds; you can leave the page while it runs.

The subsets cover all six domains and are nested: increasing from 20 to 50 keeps
the first 20 and adds 30. One run happens at a time. Starting again resumes an
interrupted run and skips images already in the library. Choosing a smaller size
does not delete images. Images that failed indexing are counted but not retried;
check the ML worker logs.

Captions use OpenRouter credit when `ML_CAPTION_ENABLED` is on and
`ML_OPENROUTER_API_KEY` is set. In deployment, the VM needs outbound HTTPS to
Wikimedia, and its managed identity needs the **Storage Blob Data Contributor**
role on the container (already required for uploads). ADMIN does not include
upload or search access; to browse the images in Search, enable the Researcher
role for yourself on the Admin tab.

The backend bundles `ml-service/evaluation/demo-manifest.json` at build time
(Maven resource plus the `evaluation` Docker build context), so rebuild the
backend after changing the manifest.

## Legacy dummy users

Fresh realm imports contain only the Keycloak provisioner service account. Older
stacks may still have the previous password-based demo logins; the API no longer
accepts them. Remove any that remain from the Admin tab; their uploads stay in
the library.

## Sources and limits

[`demo-manifest.json`](../../ml-service/evaluation/demo-manifest.json) records
creator, source, license, domain and SHA-256. See the
[attribution guide](../../ml-service/evaluation/DEMO_ATTRIBUTION.md). Retain
credits and applicable license terms, including CC BY-SA requirements.

Image embeddings stay local to the ML service. Source URLs can disappear or
change; checksum failures require reviewing the replacement and its rights.
Keep Compose volumes to preserve users, media and indexing state.
