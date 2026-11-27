# Nature showcase dataset

The local demo has **48 photographs and two short wildlife videos** across six
domains. Photos come from Wikimedia Commons; videos come from the US National
Park Service. Each asset retains its actual creator, source and license. Demo
uploaders represent archive contributors, rather than claiming authorship.

## Run and populate

Start Docker Desktop, then use Node.js 24 LTS:

```bash
./infra/start.sh
nvm use 24 # if you manage Node with nvm
./infra/seed-demo.sh
```

The script downloads checksum-pinned media, installs the existing frontend test
dependencies and Chromium, provisions local identities, and uploads through the
authenticated API and signed Blob SAS URLs. First run needs network access; allow
several minutes for downloads and model startup. Open **http://localhost:8080**
after it reports `READY 50/50` and completes verification.

| Username | Role | Preloaded collection |
|---|---|---|
| `demo.wildlife` | UPLOADER | 8 wildlife photos + bison and grizzly videos |
| `demo.plants` | UPLOADER | 8 photos: flowers, fern, trees, succulent |
| `demo.oceans` | UPLOADER | 8 photos: waves, beaches, coasts, sea ice, mangroves |
| `demo.marine` | UPLOADER | 8 photos: turtle, reef fish, coral, jellyfish, dolphin, whale, octopus, shark |
| `demo.birds` | UPLOADER | 8 photos: puffin, eagle, hummingbird, birds in flight |
| `demo.landscapes` | UPLOADER | 8 photos: mountains, streams, desert, canyon, volcano, valley |
| `demo.researcher` | RESEARCHER | Searches all READY assets; owns no uploads |

All seven use the public **local-only password `local-demo-only`**. Sign out
between identities or use separate browser profiles. Existing accounts are
preserved. `admin` can inspect the new users and grants. These fixtures must
never be used as real deployment credentials.

## Presentation walkthrough

1. Sign in as `demo.plants`: show eight READY plant assets and open **Edit** to
   show contributor and rights notes. Switch to `demo.wildlife` to show another
   owner's collection, including videos.
2. Sign in as `demo.researcher`. Search `yellow sunflower`, `sea turtle
   underwater`, `a puffin bird`, `ocean waves`, or `elephants drinking at a
   watering hole`. Preview a result and inspect its credit.
3. Try `a waterfall surrounded by green rainforest` to find the Eden Project
   waterfall photo by its visual content. This curated
   showcase is separate from the existing retrieval evaluation manifests and
   does not establish accuracy on a held-out benchmark.
4. Use the existing reliability demonstrations separately to show the SLO,
   failure responses, circuit breaker and bulkhead.

## Implementation checkpoints

**1. Curation:**
[`demo-manifest.json`](../../ml-service/evaluation/demo-manifest.json) records
domain, caption, original source title, creator, license and SHA-256. Photos
were visually reviewed; unknown dates and locations remain unset. Media bytes
live in ignored `ml-service/data/demo/`, outside Git. See the
[full attribution list](../../ml-service/evaluation/DEMO_ATTRIBUTION.md).

**2. Identities and ownership:**
[`accounts.json`](accounts.json) defines six uploaders and one researcher. The
local Keycloak Admin API creates missing identities; real OIDC browser sign-in
registers them with MediaMesh. The existing admin assigns roles through the
normal admin API. Browser password grants remain disabled. Fresh realm imports
also include these identities; existing volumes do not need to be reset.
Domain grouping uses ownership and title prefixes, without a new database schema.

**3. Upload and verification:**
[`seed-demo.mjs`](../../frontend/scripts/seed-demo.mjs) initiates uploads, PUTs
files to signed URLs, and completes them. The real worker creates Gemma image/frame embeddings and visual descriptions
and marks assets READY. Before search checks, the script fills any missing
captions and embeddings for the exact seeded IDs and verifies that their
semantic text embeddings reflect the current descriptions. The script checks all catalog counts, cross-uploader
read denial, uploader search denial, six search prompts, signed access and a
rendered sunflower preview. Uploader screens must show their expected counts.

## Reruns and limits

Reruns reuse existing fixture accounts and assets and reapply only these seven
accounts' roles. Identity collisions stop the run rather than overwrite a user.
The ignored `upload-state.json` stores asset IDs, owner IDs and checksums;
`seed-report.json` stores counts and search rankings. Tokens and signed URLs
are never saved in either file. If state is missing, assets can be rediscovered
by title and source credit; avoid editing seeded metadata before rediscovery.

Changed checksums or FAILED jobs stop the run for investigation. Interruption
after initiation but before the Blob PUT finishes can leave an UPLOADING asset
without an object: completion fails and the script stops. Inspect that asset
before retrying; the script does not silently duplicate it or bypass validation.

Seeding is restricted to the local development Compose stack and Azurite emulator;
it does not populate the cloud storage account. Keep Compose volumes to preserve the prepared demo.
Deleting volumes removes identities, objects and catalog state; repopulate a
fresh stack with the same command. Source files can disappear or change;
checksum failure requires reviewing any replacement and its rights.

Retain credits and applicable license terms, including CC BY-SA requirements.
Public-domain labels reflect the source's statement; other rights or
jurisdictional restrictions can apply. This is not National Geographic content
or an official NatGeo collection. Review source terms before publication.


### Caption generation prerequisites

Set `ML_OPENROUTER_API_KEY` in the ignored root `.env`, then run
`./infra/seed-demo.sh`. It starts/rebuilds the stack and enables captioning with
`google/gemma-4-26b-a4b-it`. The preflight validates the key and model's image
and structured-output capabilities without generating a paid completion.
No local caption model is installed. Hosted captions and search checks consume
OpenRouter credit; all image/query/metadata embeddings stay on EmbeddingGemma 2.

A missing key, unavailable hosted model or incomplete generation fails the seed
explicitly. The existing queue handles temporary provider failures with retries.

Fresh uploads generate descriptions during asynchronous processing. Existing
READY fixture assets receive any missing descriptions and current image/frame
embeddings through `mediamesh_ml.seed_enrich`; their text embeddings are then
refreshed. Existing generated descriptions and user-written metadata are kept.
Only seed asset IDs are enriched, so unrelated uploads with missing media do not
block a demo rerun. The READY wait gives a fresh dataset up to an hour for CPU
inference. Interrupted runs can resume.
