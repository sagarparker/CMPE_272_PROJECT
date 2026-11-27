import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import VectorRecord
from mediamesh_ml.database import connection
from mediamesh_ml.jobs import PostgresJobStore, StaleClaim
from mediamesh_ml.vectors import PgVectorRepository

pytestmark = pytest.mark.database
VECTOR = (1.0,) + (0.0,) * 511


@pytest.fixture(scope="module")
def settings():
    url = os.getenv("ML_PRODUCTION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set isolated ML_PRODUCTION_TEST_DATABASE_URL")
    settings = Settings(database_url=url, production_mode=True, job_retry_base_seconds=0)
    with connection(settings) as conn:
        if conn.info.dbname != "mediamesh_production_test" or conn.info.host != "postgres-test":
            pytest.fail("Production tests require isolated postgres-test/mediamesh_production_test")
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        for migration in sorted(Path("/catalog-migrations").glob("V*.sql")):
            conn.execute(migration.read_text(), prepare=False)
    return settings


@pytest.fixture
def store(settings):
    with connection(settings) as conn:
        conn.execute("TRUNCATE users,assets CASCADE")
    return PostgresJobStore(settings)


def enqueue(settings, media_type="image"):
    aid, jid, owner = uuid4(), uuid4(), uuid4()
    with connection(settings) as conn:
        conn.execute(
            "INSERT INTO users(id,issuer,subject,email,display_name) VALUES (%s,'test',%s,'','')",
            (owner, str(owner)),
        )
        conn.execute(
            "INSERT INTO assets(id,owner_id,s3_key,media_type,title,processing_status) "
            "VALUES (%s,%s,%s,%s,'Photo','PROCESSING')",
            (aid, owner, f"assets/{aid}", media_type),
        )
        conn.execute(
            "INSERT INTO index_jobs(id,asset_id,media_reference,media_type) VALUES (%s,%s,%s,%s)",
            (jid, aid, f"assets/{aid}", media_type),
        )
    return aid, jid


def state(settings, aid):
    with connection(settings) as conn:
        return conn.execute("SELECT processing_status FROM assets WHERE id=%s", (aid,)).fetchone()[
            0
        ]


def test_production_claim_is_exclusive_and_completion_is_atomic(store, settings):
    aid, jid = enqueue(settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: store.claim(), range(2)))
    job = next(c for c in claims if c is not None)
    assert sum(c is not None for c in claims) == 1
    store.complete(job, [VectorRecord(aid, VECTOR, "test-model")])
    assert state(settings, aid) == "READY"
    with connection(settings) as conn:
        assert (
            conn.execute("SELECT status FROM index_jobs WHERE id=%s", (jid,)).fetchone()[0]
            == "SUCCEEDED"
        )
        assert conn.execute("SELECT count(*) FROM asset_vectors").fetchone()[0] == 1
    with pytest.raises(StaleClaim):
        store.complete(job, [VectorRecord(aid, VECTOR, "test-model")])


def test_expired_claim_is_fenced_and_terminal_failure_updates_catalog(store, settings):
    aid, jid = enqueue(settings)
    original = store.claim()
    with connection(settings) as conn:
        conn.execute(
            "UPDATE index_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' "
            "WHERE id=%s",
            (jid,),
        )
    replacement = store.claim()
    assert replacement.attempt == 2
    with pytest.raises(StaleClaim):
        store.complete(original, [VectorRecord(aid, VECTOR, "test-model")])
    store.fail(replacement, "InvalidImage", retryable=False)
    assert state(settings, aid) == "FAILED"


def test_bad_vectors_roll_back_job_and_asset_completion(store, settings):
    aid, jid = enqueue(settings)
    job = store.claim()
    with pytest.raises(ValueError):
        store.complete(job, [VectorRecord(aid, (0.0,) * 512, "test-model")])
    assert state(settings, aid) == "PROCESSING"
    with connection(settings) as conn:
        assert (
            conn.execute("SELECT status FROM index_jobs WHERE id=%s", (jid,)).fetchone()[0]
            == "PROCESSING"
        )
        assert conn.execute("SELECT count(*) FROM asset_vectors").fetchone()[0] == 0


def test_candidate_scope_applies_before_ranking_and_similar_excludes_source(store, settings):
    aid, _ = enqueue(settings)
    bid, _ = enqueue(settings)
    for _ in range(2):
        job = store.claim()
        store.complete(job, [VectorRecord(job.asset_id, VECTOR, "test-model")])
    repo = PgVectorRepository(settings)
    assert [m.asset_id for m in repo.search_assets(VECTOR, "test-model", 1, [bid])] == [bid]
    assert repo.search_assets(VECTOR, "test-model", 1, []) == []
    assert [m.asset_id for m in repo.similar(aid, "test-model", 10, [aid, bid])] == [bid]


def test_video_completion_records_playback_copy(store, settings):
    aid, _ = enqueue(settings, "video")
    job = store.claim()
    key = f"assets/{aid}/playback/web.mp4"
    store.complete(job, [VectorRecord(aid, VECTOR, "test-model", 0.0)], playback_key=key)
    with connection(settings) as conn:
        assert conn.execute(
            "SELECT processing_status, playback_key FROM assets WHERE id=%s", (aid,)
        ).fetchone() == ("READY", key)
