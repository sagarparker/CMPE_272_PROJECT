import io
import os
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection
from mediamesh_ml.dev_ui import create_app
from mediamesh_ml.migrate import apply_migrations


@pytest.fixture
def client(tmp_path):
    url = os.getenv("ML_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set isolated ML_TEST_DATABASE_URL")
    config = Settings(database_url=url, media_root=tmp_path, media_max_bytes=1000)
    with connection(config) as conn:
        if conn.info.dbname != "mediamesh_test" or conn.info.host != "postgres-test":
            pytest.fail("UI tests require the isolated test DB")
        conn.execute("DROP SCHEMA IF EXISTS ml_dev CASCADE")
    apply_migrations(config, Path("/app/migrations"), fixture=Path("dev/bootstrap_assets.sql"))
    with connection(config) as conn:
        conn.execute("TRUNCATE assets CASCADE")
    app = create_app(config, static_root=Path("dev-ui"), evaluation_root=Path("evaluation"))
    with TestClient(app) as browser:
        yield browser


def picture():
    output = io.BytesIO()
    Image.new("RGB", (16, 16)).save(output, format="PNG")
    return output.getvalue()


def test_upload_queues_once_and_serves_media_inside_root(client):
    response = client.post("/dev/upload?filename=../../photo.png&kind=image", content=picture())
    assert response.status_code == 202
    ids = response.json()
    assert UUID(ids["assetId"])
    assets = client.get("/dev/assets").json()["assets"]
    assert len(assets) == 1 and assets[0]["status"] == "PROCESSING"
    assert assets[0]["name"] == "photo.png"
    assert client.get(f"/dev/media/{ids['assetId']}").content == picture()
    assert client.post(f"/dev/assets/{ids['assetId']}/reindex").json()["jobId"] == ids["jobId"]
    assert client.delete(f"/dev/assets/{ids['assetId']}/index").status_code == 409
    assert client.get("/dev/jobs").json()["jobs"][0]["attempts"] == 0


def test_upload_limits_empty_files_and_extension_validation(client):
    assert client.post("/dev/upload?filename=page.html", content=b"test").status_code == 400
    assert client.post("/dev/upload?filename=empty.png", content=b"").status_code == 400
    assert client.post("/dev/upload?filename=big.png", content=b"x" * 1001).status_code == 413
    assert client.get("/dev/assets").json() == {"assets": []}


def test_console_static_and_cross_origin_mutation_guard(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    response = client.post(
        "/dev/upload?filename=test.png",
        content=picture(),
        headers={"Origin": "https://unrelated.example"},
    )
    assert response.status_code == 403


def test_search_proxy_preserves_original_contract(client):
    payload = {
        "matches": [{"assetId": str(UUID(int=1)), "score": 0.8, "frameTimestampSeconds": None}]
    }
    fake = io.BytesIO(__import__("json").dumps(payload).encode())
    fake.status = 200
    with patch("mediamesh_ml.dev_ui.urllib.request.urlopen", return_value=fake) as upstream:
        response = client.post("/dev/search", json={"query": "elephants", "limit": 5})
    assert response.json() == payload
    request = upstream.call_args.args[0]
    assert request.full_url.endswith("/internal/search")
    assert client.post("/dev/search", json={"query": "elephants", "limit": 0}).status_code == 400
