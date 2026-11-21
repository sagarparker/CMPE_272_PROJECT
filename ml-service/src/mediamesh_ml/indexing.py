"""Reusable indexing preparation, separate from transactional persistence."""

from uuid import UUID

from mediamesh_ml.contracts import EmbeddingEngine, MediaSource, VectorRecord, VectorRepository


class IndexingService:
    def __init__(self, engine: EmbeddingEngine, source: MediaSource, repository: VectorRepository):
        self.engine = engine
        self.source = source
        self.repository = repository

    @property
    def model_version(self) -> str:
        identity = self.engine.identity
        return f"{identity.name}@{identity.revision}:rgb-l2-v1"

    def prepare_image(self, asset_id: UUID, reference: str) -> list[VectorRecord]:
        with self.source.materialize(reference) as path:
            embeddings = self.engine.encode_images([path])
        if len(embeddings) != 1:
            raise ValueError("Expected exactly one image embedding")
        return [VectorRecord(asset_id, embeddings[0], self.model_version)]

    def index_image(self, asset_id: UUID, reference: str) -> list[VectorRecord]:
        records = self.prepare_image(asset_id, reference)
        self.repository.replace(asset_id, self.model_version, records)
        return records
