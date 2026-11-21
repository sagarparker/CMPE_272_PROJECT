# Wildlife retrieval evaluation

This is a curated 25-image demonstration set from Wikimedia Commons, not model
training data and not a held-out scientific benchmark. Images may have appeared
in pretraining. Source search results were manually inspected before query
ranking; a saw blade and a landscape were replaced during curation. Retain the
small/obscured lions and zebras and the bird-reflection image as difficult cases.
Some images depict captive animals; they are not evidence of wild capture.

`manifest.json` records source pages, authors, individual licenses, download URLs,
and byte checksums. Follow each linked license when redistributing the images.
Downloaded samples are unmodified Commons thumbnails except for upstream
thumbnail resizing; runtime RGB/orientation/model transforms are not saved as
redistributed derivatives. `ATTRIBUTION.md` provides readable per-file credits.
The repository's source-code license does not relicense these media files.

`queries.json` contains manually reviewed relevant image IDs fixed before the
first model evaluation. Broad subject queries test baseline retrieval. The
sunset and reflection queries test attributes. Record failures; do not remove
hard examples after looking at scores. Report hit rate and mean recall at k.
No meaningful generalization claim follows from this tiny curated collection.

After building the tools image, run from `ml-service/`:

```bash
mkdir -p data/media outputs
docker compose run --rm -v "$PWD/data/media:/data/media" ml-tools python -m mediamesh_ml.dataset
docker compose run --rm -v "$PWD/outputs:/outputs" ml-tools python -m mediamesh_ml.evaluate --output /outputs/evaluation.json
```

Downloads are bounded, cached, and SHA-256 verified. A mismatch fails instead of
silently accepting changed data. The downloader makes no model calls. Respect
upstream rate limits and wait before retrying after HTTP 429. Evaluation loads
the pinned model explicitly. Set `ML_MODEL_OFFLINE=true` after the cache is
populated to verify offline operation. Model inference uses no hosted API.

## Real video samples

The separate `video-manifest.json` lists two Yellowstone clips from NPS: bison
and grizzly bear. See [VIDEO_ATTRIBUTION.md](VIDEO_ATTRIBUTION.md) for source and
usage credits. They replace unavailable Commons video downloads (HTTP 429);
the original image evaluation is unchanged. Download with the same dataset
command using `--manifest evaluation/video-manifest.json`. Run
`python -m mediamesh_ml.evaluate_video` in the tools container for offline
retrieval and actual frame timestamps. `video-baseline.json` is a small
demonstration, not a video-understanding benchmark.

Video `indexingSeconds` measures inspection/extraction plus frame encoding in
memory. It excludes model startup and database persistence; these single local
CPU observations are not throughput guarantees.
