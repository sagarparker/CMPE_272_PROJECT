"""Internal Python boundaries, not a new HTTP or production job schema."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

Embedding = tuple[float, ...]


@dataclass(frozen=True)
class ModelIdentity:
    name: str
    revision: str
    dimensions: int


def embedding_version(identity: ModelIdentity) -> str:
    return f"{identity.name}@{identity.revision}:rgb-l2-v1"


@dataclass(frozen=True)
class VectorRecord:
    asset_id: UUID
    embedding: Embedding
    model_version: str
    frame_timestamp_seconds: float | None = None


@dataclass(frozen=True)
class Match:
    asset_id: UUID
    score: float
    frame_timestamp_seconds: float | None = None


@dataclass(frozen=True)
class ClaimedJob:
    job_id: UUID
    asset_id: UUID
    media_reference: str
    media_type: Literal["image", "video"]
    claim_token: str
    attempt: int


class EmbeddingEngine(Protocol):
    def load(self) -> None: ...

    @property
    def identity(self) -> ModelIdentity: ...

    def encode_text(self, text: str) -> Embedding: ...

    def encode_images(self, paths: Sequence[Path]) -> Sequence[Embedding]: ...


class MediaSource(Protocol):
    def materialize(self, reference: str) -> AbstractContextManager[Path]:
        """Provide a local file and clean up adapter-owned temporary downloads."""
        ...


class VectorRepository(Protocol):
    def is_ready(self) -> bool: ...

    def search_assets(
        self, embedding: Embedding, model_version: str, limit: int
    ) -> Sequence[Match]:
        """Return one best frame per asset, then apply the result limit."""
        ...

    def replace(self, asset_id: UUID, model_version: str, records: Sequence[VectorRecord]) -> None:
        """Atomically replace the asset/model vector set."""
        ...

    def delete(self, asset_id: UUID) -> None: ...

    def search(self, embedding: Embedding, model_version: str, limit: int) -> Sequence[Match]: ...


class JobStore(Protocol):
    def claim(self) -> ClaimedJob | None: ...

    def complete(self, job: ClaimedJob, records: Sequence[VectorRecord]) -> None:
        """Fence stale claims; commit vectors and job/asset success atomically."""
        ...

    def fail(self, job: ClaimedJob, error: str, *, retryable: bool) -> None: ...
