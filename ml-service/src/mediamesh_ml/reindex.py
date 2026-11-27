"""Add missing embeddings for READY assets using the selected catalog model."""

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection
from mediamesh_ml.embeddings import create_engine
from mediamesh_ml.indexing import IndexingService
from mediamesh_ml.media import AzureBlobMediaSource
from mediamesh_ml.vectors import PgVectorRepository
from mediamesh_ml.video import VideoSampler


def backfill(settings: Settings, *, asset_ids=None) -> int:
    if not settings.production_mode:
        raise SystemExit("Run this command in the integrated catalog stack")
    repository = PgVectorRepository(settings)
    if not repository.is_ready():
        raise SystemExit("Apply the catalog vector migrations before reindexing")
    engine = create_engine(settings)
    indexer = IndexingService(
        engine, AzureBlobMediaSource(settings), repository, VideoSampler(settings)
    )
    with connection(settings) as conn:
        assets = conn.execute(
            """
            SELECT id, s3_key, media_type FROM public.assets a
            WHERE processing_status='READY'
                AND (%s::uuid[] IS NULL OR a.id=ANY(%s::uuid[])) AND NOT EXISTS (
                SELECT 1 FROM public.asset_vectors v
                WHERE v.asset_id=a.id AND v.model_version=%s
            ) ORDER BY a.id
            """,
            (asset_ids, asset_ids, indexer.model_version),
        ).fetchall()
    if assets:
        engine.load()
    failed = 0
    for asset_id, key, media_type in assets:
        try:
            index = indexer.index_video if media_type == "video" else indexer.index_image
            index(asset_id, key)
        except Exception as error:
            failed += 1
            print(f"Asset {asset_id} failed: {type(error).__name__}", flush=True)
    print(f"Indexed {len(assets) - failed}/{len(assets)} assets for {indexer.model_version}")
    return int(failed > 0)


def main() -> int:
    return backfill(Settings())


if __name__ == "__main__":
    raise SystemExit(main())
