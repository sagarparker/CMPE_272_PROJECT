import base64
import io
import json
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import UUID

import pytest
from PIL import Image
from pydantic import SecretStr

from mediamesh_ml.captions import VisualDescriber
from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import Match
from mediamesh_ml.openrouter import check_model, complete
from mediamesh_ml.verification import CaptionVerifier


def settings(**kwargs):
    return Settings(caption_model="google/gemma-4-26b-a4b-it",
                    openrouter_api_key=SecretStr("private-test-key"), **kwargs)


def response(text, finish="stop"):
    return io.BytesIO(json.dumps({"choices": [{"finish_reason": finish,
                                              "message": {"content": text}}]}).encode())


def test_hosted_caption_uses_bounded_images_and_secret_header(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (1600, 900), "green").save(photo)

    def respond(request, timeout):
        payload = json.loads(request.data)
        assert request.full_url == "https://openrouter.ai/api/v1/chat/completions"
        assert request.get_header("Authorization") == "Bearer private-test-key"
        assert b"private-test-key" not in request.data
        assert "options" not in payload and "think" not in payload
        assert payload["max_tokens"] == 220
        assert payload["reasoning"] == {"enabled": False}
        assert payload["provider"]["max_price"] == {"prompt": 0.2, "completion": 0.75}
        url = payload["messages"][0]["content"][1]["image_url"]["url"]
        with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
            assert max(image.size) == 768
        return response("A green field.")

    with patch("mediamesh_ml.openrouter.urlopen", side_effect=respond):
        description = VisualDescriber(settings()).describe([photo])
    assert description.text == "A green field."
    assert description.model == "google/gemma-4-26b-a4b-it"
    assert "private-test-key" not in repr(settings())


def test_hosted_verification_preserves_batch_decisions_and_cache():
    verifier = CaptionVerifier(settings())
    lion, tiger = Match(UUID(int=1), 0.9, None), Match(UUID(int=2), 0.8, None)
    captions = {lion.asset_id: "A lion rests.", tiger.asset_id: "A tiger walks."}

    def respond(request, timeout):
        payload = json.loads(request.data)
        assert payload["max_tokens"] == 160
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["provider"]["require_parameters"] is True
        assert "images" not in payload["messages"][0]
        data = json.loads(payload["messages"][0]["content"].split("\n")[-1])
        assert len(data["candidates"]) == 2
        return response('{"supported":[0]}')

    with patch("mediamesh_ml.openrouter.urlopen", side_effect=respond) as generate:
        assert verifier.filter("Lion", [lion, tiger], captions) == [lion]
        assert verifier.filter("lion", [lion, tiger], captions) == [lion]
        assert generate.call_count == 1


@pytest.mark.parametrize("text,finish", [("partial", "length"), ("", "stop"), (None, "stop")])
def test_incomplete_hosted_output_is_not_used(text, finish):
    with patch("mediamesh_ml.openrouter.urlopen", return_value=response(text, finish)):
        with pytest.raises(RuntimeError, match="incomplete or invalid"):
            complete(settings(), "describe", timeout=2)


def test_missing_key_fails_before_network_request():
    config = settings()
    config.openrouter_api_key = SecretStr("")
    with patch("mediamesh_ml.openrouter.urlopen") as generate:
        with pytest.raises(ValueError, match="ML_OPENROUTER_API_KEY"):
            complete(config, "describe")
        generate.assert_not_called()


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_http_errors_do_not_echo_provider_body_or_key(status):
    error = HTTPError("https://openrouter.ai", status, "private-test-key", {},
                      io.BytesIO(b"private-test-key request data"))
    with patch("mediamesh_ml.openrouter.urlopen", side_effect=error):
        with pytest.raises(RuntimeError) as failure:
            complete(settings(), "describe")
    assert str(status) in str(failure.value)
    assert "private-test-key" not in str(failure.value)


def test_preflight_checks_credentials_and_vision_without_generation():
    replies = [
        {"data": {"limit_remaining": 5}},
        {"data": [{"id": "google/gemma-4-26b-a4b-it",
                   "architecture": {"input_modalities": ["text", "image"]},
                   "supported_parameters": ["structured_outputs"]}]},
    ]

    def respond(request, timeout):
        assert request.get_method() == "GET"
        assert not request.full_url.endswith("/chat/completions")
        return io.BytesIO(json.dumps(replies.pop(0)).encode())

    with patch("mediamesh_ml.openrouter.urlopen", side_effect=respond):
        check_model(settings(verify_captions=True))
    assert replies == []


@pytest.mark.parametrize("model", [
    None,
    {"id": "google/gemma-4-26b-a4b-it", "architecture": {"input_modalities": ["text"]}},
    {"id": "google/gemma-4-26b-a4b-it", "architecture": {"input_modalities": ["image"]}},
])
def test_preflight_rejects_missing_model_or_capabilities(model):
    with patch("mediamesh_ml.openrouter.api_json", side_effect=[
        {"data": {"limit_remaining": 5}}, {"data": [] if model is None else [model]},
    ]):
        with pytest.raises(ValueError):
            check_model(settings(verify_captions=True))
