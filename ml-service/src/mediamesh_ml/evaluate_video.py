"""Offline video retrieval demonstration; does not modify the asset catalog."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from mediamesh_ml.config import Settings
from mediamesh_ml.dataset import read_manifest
from mediamesh_ml.embeddings import ClipEngine
from mediamesh_ml.video import VideoSampler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("evaluation/video-manifest.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = Settings()
    engine = ClipEngine(settings)
    engine.load()
    samples = []
    indexed = []
    for item in read_manifest(args.manifest):
        path = settings.media_root / item["filename"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Video sample checksum mismatch")
        started = time.perf_counter()
        sampler = VideoSampler(settings)
        metadata = sampler.probe(path)
        with sampler.extract(path) as frames:
            vectors = engine.encode_images([frame.path for frame in frames])
            aid = str(uuid5(NAMESPACE_URL, item["source_page"]))
            indexed.append((aid, vectors, [f.timestamp_seconds for f in frames]))
        samples.append(
            {
                "sampleId": item["id"],
                "assetId": aid,
                "durationSeconds": metadata.duration_seconds,
                "frameCount": len(vectors),
                "indexingSeconds": time.perf_counter() - started,
            }
        )
    queries = []
    for query in ["a herd of bison grazing in a green valley", "a bear walking through snow"]:
        vector = engine.encode_text(query)
        matches = []
        for aid, vectors, timestamps in indexed:
            scores = np.asarray(vectors) @ np.asarray(vector)
            best = int(np.argmax(scores))
            matches.append(
                {
                    "assetId": aid,
                    "score": float(scores[best]),
                    "frameTimestampSeconds": timestamps[best],
                }
            )
        queries.append(
            {
                "query": query,
                "matches": sorted(matches, key=lambda row: (-row["score"], row["assetId"])),
            }
        )
    report = {"modelVersion": engine.model_version, "samples": samples, "queries": queries}
    content = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
    print(content)


if __name__ == "__main__":
    main()
