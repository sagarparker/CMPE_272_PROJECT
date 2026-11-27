"""JSON application logs and request correlation; no request bodies or auth headers."""

import contextvars
import json
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime
from uuid import uuid4

request_id = contextvars.ContextVar("request_id", default="system")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        fields = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "requestId": getattr(record, "request_id", request_id.get()),
            "message": record.getMessage(),
        }
        if record.exc_info:
            fields["exception"] = self.formatException(record.exc_info)
        return json.dumps(fields)


def configure_logging(level=None):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(
        level=level or os.getenv("ML_LOG_LEVEL", "INFO"), handlers=[handler], force=True
    )
    logging.captureWarnings(True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # Uvicorn's URL access log may contain query strings. Use the safe completion log below.
    logging.getLogger("uvicorn.access").disabled = True
    # SDK INFO logs include complete object paths; keep only actionable warnings/errors.
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)


class RequestCorrelationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        identity = supplied if re.fullmatch(r"[a-fA-F0-9-]{16,64}", supplied) else str(uuid4())
        token = request_id.set(identity)
        started = time.monotonic()
        status = 500

        async def correlated_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", identity.encode())
                ]
            await send(message)

        try:
            await self.app(scope, receive, correlated_send)
        finally:
            logging.getLogger(__name__).info(
                "http_request_complete method=%s status=%s duration_ms=%.3f",
                scope["method"],
                status,
                (time.monotonic() - started) * 1000,
            )
            request_id.reset(token)
