"""Bounded hosted caption/verification calls; credentials never enter request bodies."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_URL = "https://openrouter.ai/api/v1"


def api_json(settings, path, *, payload=None, timeout=15):
    key = settings.openrouter_api_key.get_secret_value().strip()
    if not key:
        raise ValueError("Set ML_OPENROUTER_API_KEY for the OpenRouter provider")
    request = Request(
        BASE_URL + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as error:
        # Provider error bodies can echo request data. Keep them out of app logs.
        raise RuntimeError(f"OpenRouter request failed with HTTP {error.code}") from None
    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError("OpenRouter returned an invalid response")
    return result


def complete(settings, prompt, *, images=(), schema=None, max_tokens=220, timeout=30):
    content = prompt
    if images:
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image}}
            for image in images
        ]
    payload = {
        "model": settings.caption_model,
        "messages": [{"role": "user", "content": content}],
        "stream": False, "max_tokens": max_tokens, "temperature": 0,
        "reasoning": {"enabled": False},
        "provider": {"max_price": {
            "prompt": settings.openrouter_max_input_price,
            "completion": settings.openrouter_max_output_price,
        }},
    }
    if schema is not None:
        payload["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "search_verification", "strict": True, "schema": schema,
        }}
        payload["provider"]["require_parameters"] = True
    result = api_json(settings, "/chat/completions", payload=payload, timeout=timeout)
    try:
        choice = result["choices"][0]
        text = choice["message"]["content"]
        if choice["finish_reason"] != "stop" or not isinstance(text, str) or not text.strip():
            raise ValueError("Incomplete completion")
        return text.strip()
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("OpenRouter returned an incomplete or invalid completion") from None


def check_model(settings):
    """Validate credentials and image/structured-output capabilities without a paid call."""
    account = api_json(settings, "/key").get("data", {})
    for remaining in (account.get("limit_remaining"),
                      account.get("effective_budget", {}).get("remaining_usd")
                      if account.get("effective_budget") else None):
        if remaining is not None and remaining <= 0:
            raise ValueError("The OpenRouter API key has no remaining budget")
    models = api_json(settings, "/models").get("data", [])
    model = next((m for m in models if m.get("id") == settings.caption_model), None)
    if model is None:
        raise ValueError("Configured caption model is not available on OpenRouter")
    if "image" not in model.get("architecture", {}).get("input_modalities", []):
        raise ValueError("The configured caption model must support images")
    if (settings.verify_captions
            and "structured_outputs" not in model.get("supported_parameters", [])):
        raise ValueError("The configured verification model must support structured outputs")
