"""Reusable indexing preparation, separate from transactional persistence."""

import logging
from uuid import UUID

from mediamesh_ml.contracts import (
    EmbeddingEngine,
    MediaSource,
    VectorRecord,
    VectorRepository,
    embedding_version,
)
from mediamesh_ml.video import VideoSampler

logger = logging.getLogger(__name__)


class IndexingService:
    def __init__(
        self,
        engine: EmbeddingEngine,
        source: MediaSource,
        repository: VectorRepository,
        video_sampler: VideoSampler | None = None,
        playback=None,
        describer=None,
    ):
        self.engine = engine
        self.source = source
        self.repository = repository
        self.video_sampler = video_sampler
        self.playback = playback
        self.describer = describer

    @property
    def model_version(self) -> str:
        return embedding_version(self.engine.identity)

    def prepare_image(self, asset_id: UUID, reference: str) -> list[VectorRecord]:
        with self.source.materialize(reference) as path:
            embeddings = self.engine.encode_images([path])
        if len(embeddings) != 1:
            raise ValueError("Expected exactly one image embedding")
        return [VectorRecord(asset_id, embeddings[0], self.model_version)]

    def prepare_description(self, reference: str, media_type: str):
        if self.describer is None:
            return None
        with self.source.materialize(reference) as path:
            if media_type == "image":
                return self.describer.describe([path])
            with self.video_sampler.extract(path) as frames:
                if not frames:
                    raise ValueError("Video has no frames to describe")
                indexes = sorted({0, len(frames) // 2, len(frames) - 1})
                return self.describer.describe([frames[i].path for i in indexes])

    def index_image(self, asset_id: UUID, reference: str) -> list[VectorRecord]:
        records = self.prepare_image(asset_id, reference)
        self.repository.replace(asset_id, self.model_version, records)
        return records

    def prepare_video(self, asset_id: UUID, reference: str) -> list[VectorRecord]:
        return self.prepare_video_job(asset_id, reference)[0]

    def prepare_video_job(
        self, asset_id: UUID, reference: str
    ) -> tuple[list[VectorRecord], str | None]:
        """Embed sampled frames and, if configured, publish a browser playback copy."""
        if self.video_sampler is None:
            raise ValueError("Video sampler is not configured")
        with self.source.materialize(reference) as path:
            with self.video_sampler.extract(path) as frames:
                if not frames:
                    raise ValueError("Video extraction returned no frames")
                embeddings = self.engine.encode_images([frame.path for frame in frames])
                if len(embeddings) != len(frames):
                    raise ValueError("Expected one embedding per extracted frame")
                records = [
                    VectorRecord(asset_id, embedding, self.model_version, frame.timestamp_seconds)
                    for frame, embedding in zip(frames, embeddings, strict=True)
                ]
            playback_key = None
            if self.playback is not None:
                # Search works without the copy; previews then fall back to the original.
                try:
                    playback_key = self.playback.publish(path, reference)
                except Exception as error:
                    logger.warning(
                        "Playback copy failed for %s: %s", asset_id, type(error).__name__
                    )
        return records, playback_key

    def index_video(self, asset_id: UUID, reference: str) -> list[VectorRecord]:
        records = self.prepare_video(asset_id, reference)
        self.repository.replace(asset_id, self.model_version, records)
        return records
