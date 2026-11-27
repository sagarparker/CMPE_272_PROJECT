import json
import logging
from uuid import uuid4

from fastapi.testclient import TestClient

from mediamesh_ml.api import create_app
from mediamesh_ml.logging_json import JsonFormatter, request_id


class Search:
    def initialize(self):
        pass

    def is_ready(self):
        return True

    def search(self, query, limit):
        self.correlation = request_id.get()
        return []


def test_json_log_has_correlation_and_escapes_newlines():
    record = logging.LogRecord("test", logging.INFO, "", 0, "line1\nline2", (), None)
    token = request_id.set("test-correlation")
    try:
        encoded = JsonFormatter().format(record)
        assert "\n" not in encoded
        assert json.loads(encoded)["requestId"] == "test-correlation"
    finally:
        request_id.reset(token)


def test_request_id_is_propagated_and_invalid_values_are_replaced():
    search = Search()
    with TestClient(create_app(search_service=search)) as client:
        identity = str(uuid4())
        response = client.post(
            "/internal/search", json={"query": "elephants"}, headers={"X-Request-ID": identity}
        )
        assert response.headers["x-request-id"] == identity
        assert search.correlation == identity
        response = client.get("/health", headers={"X-Request-ID": "untrusted-log-value"})
        assert response.headers["x-request-id"] != "untrusted-log-value"
