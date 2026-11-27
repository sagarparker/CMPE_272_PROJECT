import base64
import io
from unittest.mock import patch

import pytest
from PIL import Image

from mediamesh_ml.captions import VisualDescriber
from mediamesh_ml.config import Settings


def test_caption_request_is_bounded_and_contains_only_visual_inputs(tmp_path):
    image = tmp_path / "photo.png"
    Image.new("RGB", (1200, 800), "green").save(image)
    settings = Settings()

    def respond(config, prompt, *, images, max_tokens, timeout):
        assert config is settings
        assert max_tokens == 220 and timeout == 180
        with Image.open(io.BytesIO(base64.b64decode(images[0]))) as sent:
            assert max(sent.size) == 768
        return "A tiger stands on grass beneath a blue sky."

    with patch("mediamesh_ml.captions.complete", side_effect=respond):
        description = VisualDescriber(settings).describe([image])
    assert description.text == "A tiger stands on grass beneath a blue sky."
    assert description.model == settings.caption_model


@pytest.mark.parametrize("text", ["  ", "x" * 2001])
def test_invalid_caption_output_is_not_saved(tmp_path, text):
    image = tmp_path / "photo.png"
    Image.new("RGB", (16, 16)).save(image)
    with patch("mediamesh_ml.captions.complete", return_value=text):
        with pytest.raises(RuntimeError, match="invalid description"):
            VisualDescriber(Settings()).describe([image])
