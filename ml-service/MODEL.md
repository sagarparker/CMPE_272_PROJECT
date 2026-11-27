# Embedding models

The integrated local stack now uses **EmbeddingGemma 2**. See its configuration
and indexing notes below. The CLIP and SigLIP evaluations are historical baselines.

## Original CLIP baseline

- Model: `sentence-transformers/clip-ViT-B-32`.
- Immutable revision: `327ab6726d33c0e22f920c83f2ff9e4bd38ca37f`.
- Output: 512-dimensional float vectors, L2 normalized for both modalities.
- Stored model version includes name, revision, and `rgb-l2-v1` preprocessing tag.
- Images: bounded decode, EXIF orientation, RGB conversion, then the saved CLIP
  processor's resize/crop/normalization. Batch size defaults to 8.
- Runtime: locked Sentence Transformers, Transformers, PyTorch CPU, and Pillow.
- Model source: <https://huggingface.co/sentence-transformers/clip-ViT-B-32>.
- Original model code/license context: <https://github.com/openai/CLIP>.

Inference uses downloaded weights, not a hosted API. `ClipEngine` is lazy: neither
module import nor API health downloads/loads a model. Explicit load/evaluation
commands may fetch the pinned snapshot; offline mode requires a populated cache.
CPU is the tested baseline. No GPU requirement or GPU performance claim is made.
The cache needs space for approximately 600 MB of weights plus metadata; allow
additional room for image layers, dependencies, temporary downloads, and batches.
Do not run many API workers without budgeting a model instance per process.

## Initial Docker CPU run

The checked-in `evaluation/baseline.json` records a real offline inference run
on 25 manually reviewed Commons photographs and 7 queries, at k=5. Labels were
fixed before inspecting model rankings. On this local arm64 Docker run:

- Initial model download/load: 20.93 seconds (network dependent).
- Cached offline load: 5.97 seconds.
- Encoding all 25 images: 0.93 seconds.
- Peak process RSS: approximately 1,037 MiB (not total Docker memory).
- Hit rate at 5: 7/7 queries had at least one labeled relevant result.
- Mean recall at 5: 0.943 across queries.

These are single-run observations, not latency guarantees or broad accuracy
claims. The zebra and giraffe broad queries each missed one labeled image in
the top five; a small distant zebra image ranked as a giraffe candidate. The
reflection query found its expected sample but ranked another bird above it.
Keep these cases in subsequent evaluations. Similarity scores are not confidence
probabilities. Labels are subjective, and pretraining overlap is unknown.

Vectors of different revisions/preprocessing versions must not be mixed. A new
model/dimension requires explicit reindexing and, if necessary, a new migration.

## Local SigLIP 2 trial

The optional `compose.siglip2.yaml` overlay selects
`google/siglip2-base-patch16-224` for the local API and worker. It uses the pinned
revision `75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2`, stores 768-dimensional vectors
alongside CLIP vectors, and starts with a `0.09` cosine cutoff for this model.
The worker retains the existing video-frame sampling strategy.

From the repository root, start the backend to apply the vector migration,
then index existing READY photos and videos before switching search:

```bash
docker compose up -d --build --wait backend
docker compose -f compose.yaml -f compose.siglip2.yaml run --rm --build --no-deps ml-api \
  python -m mediamesh_ml.reindex
docker compose -f compose.yaml -f compose.siglip2.yaml up -d --no-deps --wait backend ml-api ml-worker
docker compose restart frontend
```

The backfill skips assets that already have an index for the selected model.
To keep using SigLIP 2 with the infrastructure manager, set
`COMPOSE_FILE=compose.yaml:compose.siglip2.yaml`. To return to CLIP, use the
base configuration and backfill any uploads made during the trial:

```bash
docker compose -f compose.yaml run --rm --no-deps ml-api python -m mediamesh_ml.reindex
docker compose -f compose.yaml up -d --no-deps --wait backend ml-api ml-worker
docker compose restart frontend
```

## EmbeddingGemma 2 (local default)

The integrated Compose stack uses `google/embeddinggemma-2` at revision
`f9972ac22e696a105c482202646979e33e4b5a1e`, with normalized 768-dimensional vectors.
One `gemma-embed` process serves the API and worker. Only text and vision encoders
are loaded. CPU inference uses float32; float16 is unsupported by this model.
Text searches use the model's SearchQuery prompt; images use no text prompt.
Images are bounded to 768 pixels on the longest edge. Videos retain sampled-frame
retrieval. The API filters text and similar-image results below 0.67. Text search uses 80% image cosine similarity plus 20% metadata cosine similarity (title, description, species, location). Metadata uses Gemma’s Document prompt and is cached by current-text fingerprint; missing metadata scores zero. Fusion happens before the result limit. Related-image scores remain visual-only.

Start with `./infra/manage.sh start`. Existing model vectors cannot be reused:
apply backend migrations and run `docker compose run --rm --no-deps ml-api python -m mediamesh_ml.reindex` only when existing catalog media is available.
Qwen runtime code and its model cache have been removed; its applied database
migration is retained for Flyway checksum compatibility.


## Visual descriptions on upload

New uploads in the integrated stack are described once by OpenRouter using
`google/gemma-4-26b-a4b-it`. Store `ML_OPENROUTER_API_KEY` in the ignored root
`.env` (permissions 0600); the key is passed only to the ML API/worker, never the
frontend. The app sends bounded JPEGs (up to 768 pixels per edge), or up to three
sampled video frames, to the hosted model. EmbeddingGemma 2 remains local.

```bash
./infra/manage.sh start
./infra/seed-demo.sh
```

The seed checks credentials/model capabilities before uploads, using unbilled
metadata requests. Captions have a 220-token output limit, and batch verification
has a 160-token limit. Provider routing caps are `ML_OPENROUTER_MAX_INPUT_PRICE`
(default $0.20/M tokens) and `ML_OPENROUTER_MAX_OUTPUT_PRICE` ($0.75/M tokens).
A provider above these caps is not selected; insufficient capacity/budget returns
an error rather than switching to a more expensive model or silently bypassing
verification. The worker's existing job retry policy handles temporary failures.

Set `ML_CAPTION_ENABLED=false` to disable caption generation independently of
search verification. Hosted generation is the only caption/verification backend;
no local vision-model service or model download is required.

Generation occurs during asynchronous PROCESSING, with lease renewal. A temporary
caption failure follows the upload job's existing retry policy. A successful
caption, its model name, vectors, and READY state are committed in one fenced
transaction. Videos use up to three sampled frames, not the audio track or a
claim to understand every moment of the video.

Generated text lives in `assets.generated_description`, with model and generation
time alongside it. User-written `description` is preserved. Authorized asset
previews label this text as AI-generated. It joins the title, description,
species and location in cached semantic text embeddings for the existing
80% image / 20% text score. The 67 cutoff is unchanged. Existing uploads are
not automatically regenerated; run the resumable backfill below to describe them. Captions are model predictions and may contain
errors; they do not enforce every condition in a search query.


To describe previously uploaded READY photos and sampled video frames:

```bash
docker compose run --rm --no-deps ml-worker python -m mediamesh_ml.captions backfill
```

The command skips existing generated descriptions, preserves authored metadata
and all image vectors, and refreshes cached text embeddings. Each successful
asset is saved immediately so an interrupted run can resume. Missing source
files are reported individually. Use `--asset-id UUID` to target one asset.


## Query-to-caption verification

The integrated local API verifies text-search candidates against their generated
visual descriptions using the configured caption provider/model. Candidates must first meet the 0.67
hybrid cutoff. Up to 20 candidates are checked in a bounded batch; missing visual
evidence and unsupported subject/action/setting requirements are excluded. This
checks saved caption evidence, not image pixels, and is not a perfect scene
verifier. Related-image results keep their visual-only ranking.

Decisions are cached by exact query and full caption, so a changed caption is
rechecked. A verifier timeout or malformed response returns search-unavailable;
unchecked candidates are never substituted. The local Compose stack gives
verification 30 seconds (`ML_VERIFICATION_TIMEOUT_SECONDS`) and the backend
40 seconds for the full ML request (`ML_REQUEST_TIMEOUT`). Cold CPU model loading
and uncached verification add latency. `ML_VERIFY_CAPTIONS=false` disables the
additional check. Caption generation and verification share `ML_CAPTION_MODEL` and
`ML_OPENROUTER_API_KEY`. Normal image/text embedding weights remain 80/20.


Verification normalizes query casing and whitespace before decisions and cache
lookup. Explicit positive basic-color requirements additionally need matching
color evidence in the caption before model verification. Missing color evidence
rejects a candidate conservatively. Negations and alternative colors are left
to the model; background-versus-subject binding still requires model judgment.
This guard can hide a truly colored subject if its caption omits that color.


The GitHub Actions browser smoke test explicitly uses CLIP with captions and
verification disabled to skip external inference on hosted runners.
Python/database tests cover caption jobs and scoped backfills with
controlled inference responses. The complete seed and actual local Gemma
image/caption/text generation have been validated separately on Apple Silicon.
