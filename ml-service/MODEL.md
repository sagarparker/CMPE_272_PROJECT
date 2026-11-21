# Embedding model and initial evaluation

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
