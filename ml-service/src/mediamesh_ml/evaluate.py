"""In-memory image retrieval evaluation; no API or database indexing side effects."""

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

import numpy as np

from mediamesh_ml.config import Settings
from mediamesh_ml.dataset import read_manifest
from mediamesh_ml.embeddings import ClipEngine


def rank(query, vectors, sample_ids, limit):
    scores = np.asarray(vectors) @ np.asarray(query)
    return sorted(
        zip(sample_ids, scores.tolist(), strict=True), key=lambda item: (-item[1], item[0])
    )[:limit]


def evaluate(manifest: Path, queries: Path, directory: Path, settings: Settings, k: int):
    items = read_manifest(manifest)
    paths = [directory / item["filename"] for item in items]
    for item, path in zip(items, paths, strict=True):
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Missing or changed sample: {item['id']}")
    labels = json.loads(queries.read_text())["queries"]
    ids = [item["id"] for item in items]
    if any(not set(label["relevant_ids"]) <= set(ids) for label in labels):
        raise ValueError("Unknown sample ID in expected matches")
    engine = ClipEngine(settings)
    started = time.perf_counter()
    engine.load()
    loaded = time.perf_counter()
    vectors = engine.encode_images(paths)
    indexed = time.perf_counter()
    results = []
    for label in labels:
        tick = time.perf_counter()
        matches = rank(engine.encode_text(label["query"]), vectors, ids, k)
        relevant = set(label["relevant_ids"])
        found = len({sid for sid, _ in matches} & relevant)
        results.append(
            {
                "query": label["query"],
                "relevant_ids": sorted(relevant),
                "matches": [{"id": sid, "score": score} for sid, score in matches],
                "hit_at_k": bool(found),
                "recall_at_k": found / len(relevant),
                "seconds": time.perf_counter() - tick,
            }
        )
    return {
        "model_version": engine.model_version,
        "dimensions": engine.identity.dimensions,
        "device": settings.device,
        "sample_count": len(items),
        "k": k,
        "model_load_seconds": loaded - started,
        "image_encoding_seconds": indexed - loaded,
        "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "hit_rate_at_k": sum(r["hit_at_k"] for r in results) / len(results),
        "mean_recall_at_k": sum(r["recall_at_k"] for r in results) / len(results),
        "queries": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("evaluation/manifest.json"))
    parser.add_argument("--queries", type=Path, default=Path("evaluation/queries.json"))
    parser.add_argument("--directory", type=Path, default=Path("/data/media"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.k <= 100:
        parser.error("k must be between 1 and 100")
    report = evaluate(args.manifest, args.queries, args.directory, Settings(), args.k)
    content = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
    print(content)


if __name__ == "__main__":
    main()
