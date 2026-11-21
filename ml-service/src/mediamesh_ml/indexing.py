"""Reusable indexing preparation, separate from transactional persistence."""

from uuid import UUID

from mediamesh_ml.contracts import (
    EmbeddingEngine,
    MediaSource,
    VectorRecord,
    VectorRepository,
    embedding_version,
)
from mediamesh_ml.video import VideoSampler


class IndexingService:
    def __init__(
        self,
        engine: EmbeddingEngine,
        source: MediaSource,
        repository: VectorRepository,
        video_sampler: VideoSampler | None = None,
    ):
        self.engine = engine
        self.source = source
        self.repository = repository
        self.video_sampler = video_sampler

    @property
    def model_version(self) -> str:
        return embedding_version(self.engine.identity)

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

    def prepare_video(self, asset_id: UUID, reference: str) -> list[VectorRecord]:
        if self.video_sampler is None:
            raise ValueError("Video sampler is not configured")
        with self.source.materialize(reference) as path:
            with self.video_sampler.extract(path) as frames:
                if not frames:
                    raise ValueError("Video extraction returned no frames")
                embeddings = self.engine.encode_images([frame.path for frame in frames])
                if len(embeddings) != len(frames):
                    raise ValueError("Expected one embedding per extracted frame")
                return [
                    VectorRecord(asset_id, embedding, self.model_version, frame.timestamp_seconds)
                    for frame, embedding in zip(frames, embeddings, strict=True)
                ]

    def index_video(self, asset_id: UUID, reference: str) -> list[VectorRecord]:
        records = self.prepare_video(asset_id, reference)
        self.repository.replace(asset_id, self.model_version, records)
        return records
