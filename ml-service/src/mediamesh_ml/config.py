"""Environment configuration; constructing settings never loads a model or database."""

from pathlib import Path

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr = SecretStr(
        "postgresql://mediamesh:local-development-only@postgres:5432/mediamesh"
    )
    media_root: Path = Path("/data/media")
    model_cache: Path = Path("/data/models")
    model_name: str = Field(default="sentence-transformers/clip-ViT-B-32", min_length=1)
    model_revision: str | None = None  # Pin after the step 2 evaluation.
    device: str = "cpu"
    log_level: str = "INFO"
    worker_poll_seconds: float = Field(default=2.0, gt=0)
    job_max_attempts: int = Field(default=3, ge=1, le=20)
    video_max_frames: int = Field(default=8, ge=1, le=100)
    video_timeout_seconds: float = Field(default=120, gt=0)

    def model_post_init(self, __context: object) -> None:
        # Validate without including credentials in a validation error or repr.
        try:
            PostgresDsn(self.database_url.get_secret_value())
        except ValueError:
            raise ValueError("ML_DATABASE_URL must be a PostgreSQL URL") from None
