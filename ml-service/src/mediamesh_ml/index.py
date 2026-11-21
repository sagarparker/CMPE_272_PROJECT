"""Index an existing local asset explicitly; automatic job processing comes in step 6."""

import argparse
import json
from uuid import UUID

from mediamesh_ml.config import Settings
from mediamesh_ml.embeddings import ClipEngine
from mediamesh_ml.indexing import IndexingService
from mediamesh_ml.media import LocalMediaSource
from mediamesh_ml.vectors import PgVectorRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-id", type=UUID, required=True)
    parser.add_argument("--reference", help="Path relative to ML_MEDIA_ROOT")
    parser.add_argument("--media-type", choices=["image"], default="image")
    parser.add_argument("--remove", action="store_true", help="Delete all embeddings for the asset")
    args = parser.parse_args()
    if args.remove == bool(args.reference):
        parser.error("Supply either --reference or --remove")
    settings = Settings()
    repository = PgVectorRepository(settings)
    if args.remove:
        repository.delete(args.asset_id)
        print(json.dumps({"assetId": str(args.asset_id), "removed": True}))
        return
    service = IndexingService(
        ClipEngine(settings),
        LocalMediaSource(settings.media_root, max_bytes=settings.media_max_bytes),
        repository,
    )
    records = service.index_image(args.asset_id, args.reference)
    print(json.dumps({"assetId": str(args.asset_id), "vectorCount": len(records)}))


if __name__ == "__main__":
    main()
