"""Exact cosine retrieval and atomic asset/model vector replacement."""

import math
from collections.abc import Sequence
from uuid import UUID

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import Embedding, Match, VectorRecord
from mediamesh_ml.database import connection

DIMENSIONS = 512  # Default CLIP dimensions.


def vector_literal(embedding: Embedding, dimensions: int = DIMENSIONS) -> str:
    if len(embedding) != dimensions or not all(math.isfinite(x) for x in embedding):
        raise ValueError(f"Expected {dimensions} finite embedding values")
    if not math.isclose(math.sqrt(sum(x * x for x in embedding)), 1.0, abs_tol=1e-4):
        raise ValueError("Expected a unit-normalized embedding")
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def validate_model_version(model_version: str):
    if not model_version.strip():
        raise ValueError("Model version must not be blank")


def replace_in_transaction(
    conn, asset_id: UUID, model_version: str, records: Sequence[VectorRecord],
    *,
    dimensions: int = DIMENSIONS,
):
    """Caller owns the transaction, allowing future atomic job completion."""
    validate_model_version(model_version)
    prepared = []
    timestamps = set()
    for record in records:
        if record.asset_id != asset_id or record.model_version != model_version:
            raise ValueError("Record asset/model does not match the replacement scope")
        timestamp = record.frame_timestamp_seconds
        if timestamp is not None and (not math.isfinite(timestamp) or timestamp < 0):
            raise ValueError("Timestamp must be finite and nonnegative")
        if timestamp in timestamps:
            raise ValueError("Duplicate image/frame timestamp")
        timestamps.add(timestamp)
        embedding = vector_literal(record.embedding, dimensions)
        prepared.append((asset_id, timestamp, model_version, embedding))
    # Serialize replacements/deletes for the same asset, including initially empty sets.
    if not conn.execute("SELECT id FROM assets WHERE id=%s FOR UPDATE", (asset_id,)).fetchone():
        raise ValueError("Asset does not exist")
    conn.execute(
        "DELETE FROM asset_vectors WHERE asset_id=%s AND model_version=%s",
        (asset_id, model_version),
    )
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO asset_vectors"
            "(asset_id, frame_timestamp_seconds, model_version, embedding) "
            "VALUES (%s, %s, %s, %s::vector)",
            prepared,
        )


class PgVectorRepository:
    def __init__(self, settings: Settings):
        self.settings = settings

    def is_ready(self) -> bool:
        with connection(self.settings) as conn:
            row = conn.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid=to_regclass('public.asset_vectors') "
                "AND attname='embedding' AND NOT attisdropped"
            ).fetchone()
            accepted_types = {"vector"}
            if self.settings.vector_dimensions == DIMENSIONS:
                accepted_types.add(f"vector({DIMENSIONS})")
            if not row or row[0] not in accepted_types:
                return False
            conn.execute(
                "SELECT asset_id, model_version, frame_timestamp_seconds, embedding "
                "FROM public.asset_vectors LIMIT 0"
            )
        return True

    def replace(self, asset_id: UUID, model_version: str, records: Sequence[VectorRecord]) -> None:
        with connection(self.settings) as conn:
            replace_in_transaction(
                conn, asset_id, model_version, records, dimensions=self.settings.vector_dimensions
            )

    def delete(self, asset_id: UUID) -> None:
        with connection(self.settings) as conn:
            conn.execute("SELECT id FROM assets WHERE id=%s FOR UPDATE", (asset_id,))
            conn.execute("DELETE FROM asset_vectors WHERE asset_id=%s", (asset_id,))

    def search(self, embedding: Embedding, model_version: str, limit: int) -> Sequence[Match]:
        validate_model_version(model_version)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Repository limit must be an integer between 1 and 1000")
        query = vector_literal(embedding, self.settings.vector_dimensions)
        with connection(self.settings) as conn:
            rows = conn.execute(
                "SELECT asset_id, 1 - (embedding <=> %s::vector) AS score, "
                "frame_timestamp_seconds FROM asset_vectors WHERE model_version=%s "
                "ORDER BY embedding <=> %s::vector, asset_id, "
                "frame_timestamp_seconds NULLS FIRST, id LIMIT %s",
                (query, model_version, query, limit),
            ).fetchall()
        return [
            Match(asset_id=row[0], score=row[1], frame_timestamp_seconds=row[2]) for row in rows
        ]

    def search_assets(
        self, embedding: Embedding, model_version: str, limit: int, asset_ids=None
    ) -> Sequence[Match]:
        validate_model_version(model_version)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Repository limit must be an integer between 1 and 1000")
        query = vector_literal(embedding, self.settings.vector_dimensions)
        with connection(self.settings) as conn:
            rows = conn.execute(
                "SELECT asset_id, score, frame_timestamp_seconds FROM ("
                "SELECT DISTINCT ON (asset_id) asset_id, "
                "1 - (embedding <=> %s::vector) AS score, frame_timestamp_seconds "
                "FROM public.asset_vectors WHERE model_version=%s "
                "AND (%s::uuid[] IS NULL OR asset_id=ANY(%s::uuid[])) "
                "ORDER BY asset_id, embedding <=> %s::vector, "
                "frame_timestamp_seconds NULLS FIRST, id) best "
                "ORDER BY score DESC, asset_id LIMIT %s",
                (query, model_version, asset_ids, asset_ids, query, limit),
            ).fetchall()
        return [Match(row[0], row[1], row[2]) for row in rows]

    def caption_evidence(self, asset_ids):
        with connection(self.settings) as conn:
            return dict(conn.execute(
                "SELECT id,generated_description FROM assets WHERE id=ANY(%s::uuid[]) "
                "AND processing_status='READY'", (asset_ids,),
            ).fetchall())

    def refresh_metadata_vectors(self, model_version, encode_document, asset_ids=None):
        """Cache document embeddings by metadata fingerprint; never reuse stale text."""
        with connection(self.settings) as conn:
            rows = conn.execute(
                """
                SELECT a.id, concat_ws(' ', a.title, a.description, a.species,
                        a.location, a.generated_description),
                    md5(concat_ws(' ', a.title, a.description, a.species,
                        a.location, a.generated_description))
                FROM assets a LEFT JOIN asset_metadata_vectors m
                    ON m.asset_id=a.id AND m.model_version=%s
                WHERE a.processing_status='READY'
                    AND (%s::uuid[] IS NULL OR a.id=ANY(%s::uuid[]))
                    AND (m.metadata_hash IS DISTINCT FROM
                        md5(concat_ws(' ', a.title, a.description, a.species,
                        a.location, a.generated_description)))
                """, (model_version, asset_ids, asset_ids),
            ).fetchall()
        for asset_id, text, fingerprint in rows:
            if not text.strip():
                continue
            vector = vector_literal(encode_document(text), self.settings.vector_dimensions)
            with connection(self.settings) as conn:
                # Recheck metadata so an edit during inference cannot install stale vectors.
                conn.execute(
                    """
                    INSERT INTO asset_metadata_vectors
                        (asset_id, model_version, metadata_hash, embedding)
                    SELECT id, %s, %s, %s::vector FROM assets WHERE id=%s
                        AND md5(concat_ws(' ', title, description, species,
                            location, generated_description))=%s
                    ON CONFLICT (asset_id, model_version) DO UPDATE SET
                        metadata_hash=EXCLUDED.metadata_hash, embedding=EXCLUDED.embedding
                    """, (model_version, fingerprint, vector, asset_id, fingerprint),
                )

    def search_hybrid(
        self, embedding: Embedding, model_version: str, text_query: str, limit: int,
        asset_ids=None,
    ) -> Sequence[Match]:
        """Fuse image and current metadata cosine scores before limiting candidates."""
        validate_model_version(model_version)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Repository limit must be an integer between 1 and 1000")
        query = vector_literal(embedding, self.settings.vector_dimensions)
        with connection(self.settings) as conn:
            rows = conn.execute(
                """
                WITH best AS (
                    SELECT DISTINCT ON (v.asset_id) v.asset_id,
                        1 - (v.embedding <=> %s::vector) AS image_score,
                        v.frame_timestamp_seconds,
                        coalesce(1 - (m.embedding <=> %s::vector), 0) AS text_score
                    FROM public.asset_vectors v JOIN public.assets a ON a.id=v.asset_id
                    LEFT JOIN asset_metadata_vectors m ON m.asset_id=a.id
                        AND m.model_version=v.model_version
                        AND m.metadata_hash=md5(concat_ws(' ',
                            a.title, a.description, a.species, a.location, a.generated_description))
                    WHERE v.model_version=%s AND a.processing_status='READY'
                        AND (%s::uuid[] IS NULL OR v.asset_id=ANY(%s::uuid[]))
                    ORDER BY v.asset_id, v.embedding <=> %s::vector,
                        v.frame_timestamp_seconds NULLS FIRST, v.id
                )
                SELECT asset_id, 0.8 * image_score + 0.2 * text_score AS score,
                    frame_timestamp_seconds FROM best
                ORDER BY score DESC, asset_id LIMIT %s
                """, (query, query, model_version, asset_ids, asset_ids, query, limit),
            ).fetchall()
        return [Match(row[0], row[1], row[2]) for row in rows]

    def similar(self, asset_id, model_version, limit, asset_ids=None):
        with connection(self.settings) as conn:
            # An image vector, or a sampled video frame, provides the reference.
            row = conn.execute(
                "SELECT embedding::text FROM asset_vectors WHERE asset_id=%s AND model_version=%s "
                "ORDER BY frame_timestamp_seconds NULLS FIRST LIMIT 1",
                (asset_id, model_version),
            ).fetchone()
        if row is None:
            raise ValueError("Asset has no vectors")
        import json

        matches = self.search_assets(tuple(json.loads(row[0])), model_version, limit + 1, asset_ids)
        return [match for match in matches if match.asset_id != asset_id][:limit]
