"""Exact cosine retrieval and atomic asset/model vector replacement."""

import math
from collections.abc import Sequence
from uuid import UUID

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import Embedding, Match, VectorRecord
from mediamesh_ml.database import connection

DIMENSIONS = 512  # V300 schema; a dimension change requires a new migration.


def vector_literal(embedding: Embedding) -> str:
    if len(embedding) != DIMENSIONS or not all(math.isfinite(x) for x in embedding):
        raise ValueError("Expected 512 finite embedding values")
    if not math.isclose(math.sqrt(sum(x * x for x in embedding)), 1.0, abs_tol=1e-4):
        raise ValueError("Expected a unit-normalized embedding")
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def validate_model_version(model_version: str):
    if not model_version.strip():
        raise ValueError("Model version must not be blank")


def replace_in_transaction(
    conn, asset_id: UUID, model_version: str, records: Sequence[VectorRecord]
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
        prepared.append((asset_id, timestamp, model_version, vector_literal(record.embedding)))
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

    def replace(self, asset_id: UUID, model_version: str, records: Sequence[VectorRecord]) -> None:
        with connection(self.settings) as conn:
            replace_in_transaction(conn, asset_id, model_version, records)

    def delete(self, asset_id: UUID) -> None:
        with connection(self.settings) as conn:
            conn.execute("SELECT id FROM assets WHERE id=%s FOR UPDATE", (asset_id,))
            conn.execute("DELETE FROM asset_vectors WHERE asset_id=%s", (asset_id,))

    def search(self, embedding: Embedding, model_version: str, limit: int) -> Sequence[Match]:
        validate_model_version(model_version)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Repository limit must be an integer between 1 and 1000")
        query = vector_literal(embedding)
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
