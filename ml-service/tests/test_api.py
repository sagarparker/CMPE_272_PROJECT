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
        if not self.is_ready():
            from mediamesh_ml.search import SearchUnavailable

            raise SearchUnavailable("Unavailable")
        self.last_request = (query, limit)
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


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": None},
        {"query": 42},
        {"query": "x" * 1001},
        {"query": "lion", "limit": 0},
        {"query": "lion", "limit": 101},
        {"query": "lion", "limit": True},
        {"query": "lion", "limit": 1.5},
        {"query": "lion", "limit": "2"},
        {"query": "lion", "mediaType": "video"},
        [],
    ],
)
def test_search_invalid_inputs_follow_400_contract(client, body):
    response = client.post("/internal/search", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


def test_empty_search_and_default_limit(client):
    response = client.post("/internal/search", json={"query": "  elephants  "})
    assert response.status_code == 200
    assert response.json() == {"matches": []}
    assert client.app.state.search_service.last_request == ("elephants", 20)


def test_response_preserves_exact_fields_and_null_image_timestamps():
    from uuid import UUID

    from mediamesh_ml.contracts import Match

    class Results(FakeSearch):
        def search(self, query, limit):
            return [Match(UUID(int=1), 0.83, 3.25), Match(UUID(int=2), -0.1, None)]

    with TestClient(create_app(search_service=Results())) as client:
        response = client.post("/internal/search", json={"query": "wildlife", "limit": 2})
        assert response.json() == {
            "matches": [
                {"assetId": str(UUID(int=1)), "score": 0.83, "frameTimestampSeconds": 3.25},
                {"assetId": str(UUID(int=2)), "score": -0.1, "frameTimestampSeconds": None},
            ]
        }


def test_unavailable_search_is_503_while_liveness_stays_200():
    with TestClient(create_app(search_service=FakeSearch(available=False))) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        response = client.post("/internal/search", json={"query": "elephants"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SEARCH_UNAVAILABLE"


def test_failed_model_startup_is_not_ready():
    class Broken(FakeSearch):
        def initialize(self):
            raise OSError("secret connection detail")

    with TestClient(create_app(search_service=Broken())) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.post("/internal/search", json={"query": "bear"}).status_code == 503


def test_invalid_query_and_internal_errors_have_distinct_status_codes():
    from mediamesh_ml.contracts import InvalidQuery

    class Failing(FakeSearch):
        def search(self, query, limit):
            raise (
                InvalidQuery("secret input") if query == "long" else ValueError("secret db detail")
            )

    with TestClient(create_app(search_service=Failing())) as client:
        for query, code in [("long", 400), ("normal", 503)]:
            response = client.post("/internal/search", json={"query": query})
            assert response.status_code == code
            assert "secret" not in response.text


def test_openapi_documents_400_instead_of_422(client):
    responses = client.get("/openapi.json").json()["paths"]["/internal/search"]["post"]["responses"]
    assert "400" in responses and "503" in responses
    assert "422" not in responses
