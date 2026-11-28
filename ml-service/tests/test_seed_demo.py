"""Exercise seed retries and dummy-account cleanup against the migrated catalog."""

import os
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection
from mediamesh_ml.seed_demo import ISSUER, remove_legacy_users, seed_image

pytestmark = pytest.mark.database


@pytest.fixture
def catalog():
    url = os.getenv("ML_PRODUCTION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set isolated ML_PRODUCTION_TEST_DATABASE_URL")
    settings = Settings(database_url=url, production_mode=True)
    with connection(settings) as conn:
        assert conn.info.dbname == "mediamesh_production_test"
        assert conn.info.host == "postgres-test"
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        for migration in sorted(Path("/catalog-migrations").glob("V*.sql")):
            conn.execute(migration.read_text(), prepare=False)
        owner = uuid4()
        conn.execute(
            "INSERT INTO users(id,issuer,subject,email,display_name,primary_admin) "
            "VALUES (%s,%s,'google-admin','owner@example.org','Owner',true)", (owner, ISSUER),
        )
    return settings, owner


@pytest.fixture
def image(tmp_path):
    (tmp_path / "example.jpg").write_bytes(b"image bytes")
    return {
        "id": "example", "sha256": "a" * 64, "domain": "wildlife", "title": "Example",
        "filename": "example.jpg", "license": "CC0", "creator": "Creator",
        "source_page": "https://example.org/source",
    }


def test_seed_retry_reuses_asset_and_queues_once(catalog, image, tmp_path):
    settings, owner = catalog
    client = Mock()
    aid = seed_image(settings, client, owner, image, tmp_path)
    assert seed_image(settings, client, owner, image, tmp_path) == aid
    client.get_blob_client.return_value.upload_blob.assert_called_once()
    with connection(settings) as conn:
        assert conn.execute("SELECT count(*) FROM assets").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM index_jobs").fetchone()[0] == 1
        assert conn.execute("SELECT owner_id,processing_status FROM assets").fetchone() == (
            owner, "PROCESSING",
        )


def test_interrupted_blob_upload_resumes_before_queueing(catalog, image, tmp_path):
    settings, owner = catalog
    client = Mock()
    client.get_blob_client.return_value.upload_blob.side_effect = OSError("interrupted PUT")
    with pytest.raises(OSError):
        seed_image(settings, client, owner, image, tmp_path)
    with connection(settings) as conn:
        assert conn.execute("SELECT processing_status FROM assets").fetchone() == ("UPLOADING",)
        assert conn.execute("SELECT count(*) FROM index_jobs").fetchone()[0] == 0
    client.get_blob_client.return_value.upload_blob.side_effect = None
    seed_image(settings, client, owner, image, tmp_path)
    with connection(settings) as conn:
        assert conn.execute("SELECT count(*) FROM assets").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM index_jobs").fetchone()[0] == 1


def test_cleanup_transfers_assets_and_reuses_old_seed(catalog, image, tmp_path, monkeypatch):
    settings, owner = catalog
    legacy = uuid4()
    with connection(settings) as conn:
        conn.execute(
            "INSERT INTO users(id,issuer,subject,email,display_name) "
            "VALUES (%s,%s,'old-subject','demo.wildlife@mediamesh.local','Dummy')",
            (legacy, ISSUER),
        )
        conn.execute("INSERT INTO user_roles VALUES (%s,'UPLOADER')", (legacy,))
        conn.execute("INSERT INTO api_sessions VALUES ('legacy',%s,now(),now(),false)", (legacy,))
    aid = seed_image(settings, Mock(), legacy, image, tmp_path)

    def provider(route, token=None, data=None, method=None):
        if data:
            return {"access_token": "fixture-token"}
        if route.endswith("username=demo.wildlife"):
            return [{"id": "old-subject", "email": "demo.wildlife@mediamesh.local"}]
        return []

    mock_provider = Mock(side_effect=provider)
    monkeypatch.setattr("mediamesh_ml.seed_demo.provider", mock_provider)
    remove_legacy_users(settings, owner, {"accounts": [
        {"username": "demo.wildlife", "email": "demo.wildlife@mediamesh.local"},
    ]})
    with connection(settings) as conn:
        assert conn.execute("SELECT deleted_at IS NOT NULL FROM users WHERE id=%s", (legacy,)
                            ).fetchone()[0]
        assert conn.execute("SELECT count(*) FROM user_roles WHERE user_id=%s", (legacy,)
                            ).fetchone()[0] == 0
        assert conn.execute("SELECT revoked FROM api_sessions WHERE session_id='legacy'"
                            ).fetchone()[0]
        row = conn.execute("SELECT owner_id FROM assets WHERE id=%s", (aid,)).fetchone()
        assert row == (owner,)
    client = Mock()
    assert seed_image(settings, client, owner, image, tmp_path) == aid
    client.get_blob_client.assert_not_called()
    mock_provider.assert_any_call("/admin/realms/mediamesh/users/old-subject",
                                  "fixture-token", method="DELETE")


def test_google_linked_legacy_username_is_preserved(catalog, monkeypatch):
    settings, owner = catalog

    def provider(route, token=None, data=None, method=None):
        if data:
            return {"access_token": "fixture-token"}
        if route.endswith("federated-identity"):
            return [{"identityProvider": "google"}]
        return [{"id": "google-user", "email": "demo.wildlife@mediamesh.local"}]

    mock_provider = Mock(side_effect=provider)
    monkeypatch.setattr("mediamesh_ml.seed_demo.provider", mock_provider)
    with pytest.raises(ValueError, match="no longer matches"):
        remove_legacy_users(settings, owner, {"accounts": [
            {"username": "demo.wildlife", "email": "demo.wildlife@mediamesh.local"},
        ]})
    assert not any(call.kwargs.get("method") == "DELETE" for call in mock_provider.call_args_list)
