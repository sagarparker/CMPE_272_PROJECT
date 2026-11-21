import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from mediamesh_ml.api import create_app


class FakeSearch:
    def __init__(self, available=True):
        self.available = available
        self.initialized = False

    def initialize(self):
        self.initialized = True

    def is_ready(self):
        return self.initialized and self.available

    def search(self, query, limit):
        return []


@pytest.fixture
def client():
    with TestClient(create_app(search_service=FakeSearch())) as client:
        yield client


def test_liveness_and_honest_readiness(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_future_routes_are_not_fake_implementations(client):
    for path in ("/internal/similar", "/internal/embed-media"):
        response = client.post(path, json={})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "HTTP_404"


class ProbeRequest(BaseModel):
    limit: int


def test_validation_maps_to_400_without_echoing_input():
    app = create_app(search_service=FakeSearch())

    # Test-only route exercises the shared handler before search is implemented.
    @app.post("/validation-probe")
    def probe(body: ProbeRequest):
        return body

    with TestClient(app) as client:
        response = client.post("/validation-probe", json={"limit": "private-input"})
        assert response.status_code == 400
        assert response.json() == {
            "error": {"code": "INVALID_INPUT", "message": "Invalid request input"}
        }
        assert "private-input" not in response.text
        assert (
            client.post(
                "/validation-probe", content="{broken", headers={"Content-Type": "application/json"}
            ).status_code
            == 400
        )


def test_method_not_allowed_preserves_allow_header(client):
    response = client.post("/health")
    assert response.status_code == 405
    assert "GET" in response.headers["allow"]
