"""Environment configuration; constructing settings never loads a model or database."""

from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr = SecretStr(
        "postgresql://mediamesh:local-development-only@postgres:5432/mediamesh"
    )
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    db_statement_timeout_ms: int = Field(default=15000, ge=1, le=300000)
    production_mode: bool = False
    azure_storage_account: str = Field(default="", pattern=r"^([a-z0-9]{3,24})?$")
    azure_storage_container: str = "mediamesh"
    azure_emulator_endpoint: str = ""
    media_root: Path = Path("/data/media")
    media_max_bytes: int = Field(default=100_000_000, ge=1)
    model_cache: Path = Path("/data/models")
    embedding_model: Literal["clip", "siglip2", "embeddinggemma2"] = "clip"
    gemma_embedding_url: str = "http://gemma-embed:8000"
    search_min_similarity: float = Field(default=0.67, ge=-1, le=1)
    verify_captions: bool = False
    verification_timeout_seconds: int = Field(default=6, ge=1, le=30)
    caption_enabled: bool = False
    caption_url: str = "http://host.docker.internal:11434"
    caption_model: str = "gemma4:e2b-it-q4_K_M"
    caption_timeout_seconds: int = Field(default=180, ge=1, le=600)
    model_name: str = Field(default="sentence-transformers/clip-ViT-B-32", min_length=1)
    model_revision: str = "327ab6726d33c0e22f920c83f2ff9e4bd38ca37f"
    embedding_dimensions: int = Field(default=512, ge=1)
    embedding_batch_size: int = Field(default=8, ge=1, le=128)
    model_offline: bool = False
    device: str = "cpu"
    log_level: str = "INFO"
    worker_poll_seconds: float = Field(default=2.0, gt=0)
    job_lease_seconds: float = Field(default=60, ge=1, le=3600)
    job_retry_base_seconds: float = Field(default=2, ge=0, le=300)
    job_retry_max_seconds: float = Field(default=60, ge=0, le=3600)
    job_max_attempts: int = Field(default=3, ge=1, le=20)
    video_max_frames: int = Field(default=8, ge=1, le=100)
    video_max_duration_seconds: float = Field(default=180, gt=0)
    video_max_pixels: int = Field(default=8_294_400, ge=1)
    video_temp_root: Path = Path("/tmp")
    video_timeout_seconds: float = Field(default=120, gt=0)
    video_playback_max_edge: int = Field(default=1920, ge=16, le=3840)
    video_playback_timeout_seconds: float = Field(default=300, gt=0)

    @property
    def vector_dimensions(self) -> int:
        if self.embedding_model == "embeddinggemma2":
            return 768
        return 768 if self.embedding_model == "siglip2" else self.embedding_dimensions

    def model_post_init(self, __context: object) -> None:
        # Validate without including credentials in a validation error or repr.
        try:
            PostgresDsn(self.database_url.get_secret_value())
        except ValueError:
            raise ValueError("ML_DATABASE_URL must be a PostgreSQL URL") from None
