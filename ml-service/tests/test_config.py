import pytest
from pydantic import ValidationError

from mediamesh_ml.config import Settings


def test_environment_overrides_and_secret_redaction(monkeypatch):
    monkeypatch.setenv("ML_DATABASE_URL", "postgresql://user:private-password@db/library")
    monkeypatch.setenv("ML_VIDEO_MAX_FRAMES", "12")
    settings = Settings()
    assert settings.video_max_frames == 12
    assert "private-password" not in repr(settings)


@pytest.mark.parametrize("value", ["0", "-1", "101"])
def test_frame_limit_is_bounded(monkeypatch, value):
    monkeypatch.setenv("ML_VIDEO_MAX_FRAMES", value)
    with pytest.raises(ValidationError):
        Settings()


def test_invalid_database_url_does_not_echo_credentials(monkeypatch):
    monkeypatch.setenv("ML_DATABASE_URL", "http://user:private-password@host")
    with pytest.raises(ValidationError) as error:
        Settings()
    assert "private-password" not in str(error.value)
