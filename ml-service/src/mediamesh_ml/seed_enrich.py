"""Finish model-derived data for explicitly selected local demo assets."""

import argparse
import json
import sys
from uuid import UUID

from mediamesh_ml.captions import backfill as caption_backfill
from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection
from mediamesh_ml.embeddings import create_engine
from mediamesh_ml.openrouter import check_model
from mediamesh_ml.reindex import backfill as embedding_backfill


def enrich(settings, asset_ids):
    if not settings.production_mode or settings.embedding_model != "embeddinggemma2":
        raise ValueError("Demo enrichment requires the integrated Gemma catalog")
    ids = list(dict.fromkeys(UUID(str(value)) for value in asset_ids))
    if not ids or len(ids) > 1000:
        raise ValueError("Supply 1-1000 explicit demo asset IDs")
    with connection(settings) as conn:
        ready = conn.execute(
            "SELECT count(*) FROM assets WHERE id=ANY(%s::uuid[]) "
            "AND processing_status='READY'", (ids,),
        ).fetchone()[0]
    if ready != len(ids):
        raise ValueError("Every selected demo asset must exist and be READY")
    if embedding_backfill(settings, asset_ids=ids):
        raise RuntimeError("Demo image/frame embedding generation failed")
    if caption_backfill(settings, asset_ids=ids):
        raise RuntimeError("Demo description generation failed")
    version = create_engine(settings).model_version
    with connection(settings) as conn:
        verified = conn.execute(
            """
            SELECT count(*) FROM assets a WHERE a.id=ANY(%s::uuid[])
                AND a.processing_status='READY'
                AND nullif(trim(a.generated_description),'') IS NOT NULL
                AND EXISTS (SELECT 1 FROM asset_vectors v
                    WHERE v.asset_id=a.id AND v.model_version=%s)
                AND EXISTS (SELECT 1 FROM asset_metadata_vectors m
                    WHERE m.asset_id=a.id AND m.model_version=%s
                        AND m.metadata_hash=md5(concat_ws(' ',a.title,a.description,
                            a.species,a.location,a.generated_description)))
            """, (ids, version, version),
        ).fetchone()[0]
    if verified != len(ids):
        raise RuntimeError("Demo captions or current embeddings are incomplete")
    print(json.dumps({"verified": verified, "modelVersion": version}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-model", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.check_model:
        check_model(settings)
        print("OpenRouter visual-description model is ready (no generation charge)")
    else:
        enrich(settings, json.load(sys.stdin))


if __name__ == "__main__":
    main()
