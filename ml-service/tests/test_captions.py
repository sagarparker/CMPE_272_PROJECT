import base64
import io
import json
from unittest.mock import patch

import pytest
from PIL import Image

from mediamesh_ml.captions import VisualDescriber
from mediamesh_ml.config import Settings


def test_caption_request_is_bounded_and_contains_only_visual_inputs(tmp_path):
    image = tmp_path / "photo.png"
    Image.new("RGB", (1200, 800), "green").save(image)
    settings = Settings()

    def respond(request, timeout):
        body = json.loads(request.data)
        assert request.full_url.endswith("/api/chat")
        assert body["model"] == settings.caption_model
        assert not body["stream"] and not body["think"]
        assert timeout == 180
        with Image.open(io.BytesIO(base64.b64decode(body["messages"][0]["images"][0]))) as sent:
            assert max(sent.size) == 768
        return io.BytesIO(json.dumps({
            "done": True, "message": {"content": "A tiger stands on grass beneath a blue sky."}
        }).encode())

    with patch("mediamesh_ml.captions.urlopen", side_effect=respond):
        description = VisualDescriber(settings).describe([image])
    assert description.text == "A tiger stands on grass beneath a blue sky."
    assert description.model == settings.caption_model


@pytest.mark.parametrize("response", [
    {"done": False, "message": {"content": "Partial"}},
    {"done": True, "message": {"content": "  "}},
    {"done": True, "message": {"content": "x" * 2001}},
])
def test_invalid_caption_output_is_not_saved(tmp_path, response):
    image = tmp_path / "photo.png"
    Image.new("RGB", (16, 16)).save(image)
    reply = io.BytesIO(json.dumps(response).encode())
    with patch("mediamesh_ml.captions.urlopen", return_value=reply):
        with pytest.raises(RuntimeError, match="invalid description"):
            VisualDescriber(Settings()).describe([image])
