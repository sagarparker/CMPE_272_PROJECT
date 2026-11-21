import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import ModelIdentity, VectorRecord
from mediamesh_ml.database import connection
from mediamesh_ml.indexing import IndexingService
from mediamesh_ml.jobs import LocalJobStore, StaleClaim, initialize_local_jobs
from mediamesh_ml.media import LocalMediaSource
from mediamesh_ml.migrate import apply_migrations
from mediamesh_ml.vectors import PgVectorRepository
from mediamesh_ml.worker import Worker

pytestmark = pytest.mark.database
VECTOR = (1.0,) + (0.0,) * 511


@pytest.fixture(scope="module")
def settings():
    url = os.getenv("ML_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set isolated ML_TEST_DATABASE_URL")
    config = Settings(database_url=url, job_retry_base_seconds=0)
    with connection(config) as conn:
        if conn.info.dbname != "mediamesh_test" or conn.info.host != "postgres-test":
            pytest.fail("Jobs tests require the isolated Compose test database")
        conn.execute("DROP SCHEMA IF EXISTS ml_dev CASCADE")
    apply_migrations(config, Path("/app/migrations"), fixture=Path("dev/bootstrap_assets.sql"))
    initialize_local_jobs(config)
    return config


@pytest.fixture
def store(settings):
    with connection(settings) as conn:
        conn.execute("TRUNCATE public.assets CASCADE")
    return LocalJobStore(settings)


def add_asset(settings):
    aid = uuid4()
    with connection(settings) as conn:
        conn.execute("INSERT INTO assets VALUES (%s)", (aid,))
    return aid


def state(settings, aid):
    with connection(settings) as conn:
        return conn.execute(
            "SELECT processing_status FROM ml_dev.asset_states WHERE asset_id=%s", (aid,)
        ).fetchone()[0]


def expire(settings, jid):
    with connection(settings) as conn:
        conn.execute(
            "UPDATE ml_dev.index_jobs SET lease_expires_at=clock_timestamp()-"
            "interval '1 second' WHERE id=%s",
            (jid,),
        )


def test_enqueue_is_idempotent_and_claim_is_exclusive(store, settings):
    aid = add_asset(settings)
    with ThreadPoolExecutor(max_workers=3) as executor:
        ids = list(executor.map(lambda _: store.enqueue(aid, "image.png", "image"), range(3)))
    assert len(set(ids)) == 1
    with pytest.raises(ValueError, match="different"):
        store.enqueue(aid, "different.png", "image")
    with ThreadPoolExecutor(max_workers=3) as executor:
        claims = list(executor.map(lambda _: store.claim(), range(3)))
    assert sum(c is not None for c in claims) == 1
    assert store.status(ids[0])["attempts"] == 1
    assert state(settings, aid) == "PROCESSING"


def test_retry_and_terminal_attempts(store, settings):
    store.settings = settings.model_copy(update={"job_max_attempts": 2})
    aid = add_asset(settings)
    jid = store.enqueue(aid, "image.png", "image")
    for attempt in [1, 2]:
        job = store.claim()
        assert job.attempt == attempt
        store.fail(job, "TemporaryFailure", retryable=True)
    assert store.status(jid)["status"] == "FAILED"
    assert state(settings, aid) == "FAILED"
    assert store.claim() is None


def test_retry_backoff_and_error_redaction(store, settings):
    store.settings = settings.model_copy(update={"job_retry_base_seconds": 60})
    jid = store.enqueue(add_asset(settings), "image.png", "image")
    store.fail(store.claim(), "s3://secret-token/private/path", retryable=True)
    assert store.status(jid)["lastError"] == "ProcessingError"
    assert store.claim() is None


def test_expired_claim_is_recovered_and_former_owner_cannot_write(store, settings):
    aid = add_asset(settings)
    jid = store.enqueue(aid, "image.png", "image")
    old = store.claim()
    assert store.renew(old)
    expire(settings, jid)
    assert not store.renew(old)
    new = store.claim()
    assert new.job_id == old.job_id and new.claim_token != old.claim_token
    assert new.attempt == 2
    with pytest.raises(StaleClaim):
        store.complete(old, [VectorRecord(aid, VECTOR, "model")])
    with pytest.raises(StaleClaim):
        store.fail(old, "Error", retryable=True)
    store.complete(new, [VectorRecord(aid, VECTOR, "model")])
    assert store.status(jid)["status"] == "SUCCEEDED"
    assert state(settings, aid) == "READY"


def test_expired_final_attempt_fails_without_new_claim(store, settings):
    store.settings = settings.model_copy(update={"job_max_attempts": 1})
    aid = add_asset(settings)
    jid = store.enqueue(aid, "image.png", "image")
    store.claim()
    expire(settings, jid)
    assert store.claim() is None
    assert store.status(jid)["lastError"] == "LeaseExpired"
    assert state(settings, aid) == "FAILED"


def test_completion_rollback_preserves_vectors_and_processing_state(store, settings):
    aid = add_asset(settings)
    repo = PgVectorRepository(settings)
    repo.replace(aid, "model", [VectorRecord(aid, VECTOR, "model")])
    jid = store.enqueue(aid, "image.png", "image")
    job = store.claim()
    with pytest.raises(ValueError):
        store.complete(job, [VectorRecord(aid, (0.0,) * 512, "model")])
    with pytest.raises(ValueError, match="empty"):
        store.complete(job, [])
    assert state(settings, aid) == "PROCESSING"
    assert store.status(jid)["status"] == "PROCESSING"
    assert repo.search(VECTOR, "model", 1)[0].score == pytest.approx(1)


class Engine:
    identity = ModelIdentity("test-model", "revision", 512)

    def encode_images(self, paths):
        from mediamesh_ml.images import prepare_image

        for path in paths:
            with prepare_image(path):
                pass
        return [VECTOR for _ in paths]


def indexer(settings, directory):
    return IndexingService(Engine(), LocalMediaSource(directory), PgVectorRepository(settings))


def test_worker_missing_file_retries_then_succeeds(store, settings, tmp_path):
    aid = add_asset(settings)
    jid = store.enqueue(aid, "later.png", "image")
    worker = Worker(store, indexer(settings, tmp_path), settings)
    assert worker.run_once()
    assert store.status(jid)["status"] == "PENDING"
    Image.new("RGB", (16, 16)).save(tmp_path / "later.png")
    assert worker.run_once()
    assert store.status(jid)["status"] == "SUCCEEDED"
    assert store.status(jid)["attempts"] == 2
    assert state(settings, aid) == "READY"
    assert not worker.run_once()


def test_heartbeat_renews_while_preparing(store, settings, tmp_path, monkeypatch):
    config = settings.model_copy(update={"job_lease_seconds": 1})
    store.settings = config
    aid = add_asset(settings)
    store.enqueue(aid, "image.png", "image")
    Image.new("RGB", (16, 16)).save(tmp_path / "image.png")
    service = indexer(settings, tmp_path)
    renewed = threading.Event()
    original_renew = store.renew
    original_prepare = service.prepare_image

    def renew(job):
        result = original_renew(job)
        renewed.set()
        return result

    def prepare(*args):
        assert renewed.wait(3), "Heartbeat did not run"
        return original_prepare(*args)

    monkeypatch.setattr(store, "renew", renew)
    monkeypatch.setattr(service, "prepare_image", prepare)
    Worker(store, service, config).run_once()
    assert state(settings, aid) == "READY"


def test_shutdown_finishes_current_job_without_claiming_another(store, settings, tmp_path):
    aid = add_asset(settings)
    other = add_asset(settings)
    first = store.enqueue(aid, "image.png", "image")
    second = store.enqueue(other, "image.png", "image")
    Image.new("RGB", (16, 16)).save(tmp_path / "image.png")
    stop = threading.Event()
    service = indexer(settings, tmp_path)
    original = service.prepare_image

    def prepare(*args):
        stop.set()
        return original(*args)

    service.prepare_image = prepare
    Worker(store, service, settings).run(stop)
    assert store.status(first)["status"] == "SUCCEEDED"
    assert store.status(second)["status"] == "PENDING"
