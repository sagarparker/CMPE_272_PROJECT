import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import VectorRecord, embedding_version
from mediamesh_ml.database import connection
from mediamesh_ml.embeddings import SIGLIP2_ID
from mediamesh_ml.gemma_embeddings import GEMMA_ID
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


@pytest.mark.parametrize(
    ("embedding_model", "identity"), [("siglip2", SIGLIP2_ID), ("embeddinggemma2", GEMMA_ID)]
)
def test_model_vectors_coexist_and_are_ranked_separately(
    store, settings, embedding_model, identity
):
    first, _ = enqueue(settings, "video")
    clip = PgVectorRepository(settings)
    clip.replace(first, "test-model", [VectorRecord(first, VECTOR, "test-model", 0.0)])

    trial = settings.model_copy(update={"embedding_model": embedding_model})
    jobs = PostgresJobStore(trial)
    job = jobs.claim()
    assert job.asset_id == first
    version = embedding_version(identity)
    vector = (1.0,) + (0.0,) * (identity.dimensions - 1)
    jobs.complete(job, [VectorRecord(first, vector, version, 3.0)])
    second, _ = enqueue(settings)
    clip.replace(second, "test-model", [VectorRecord(second, VECTOR, "test-model")])

    trial_repository = PgVectorRepository(trial)
    assert trial_repository.is_ready()
    assert {m.asset_id for m in clip.search_assets(VECTOR, "test-model", 5)} == {first, second}
    matches = trial_repository.search_assets(vector, version, 5)
    assert [(m.asset_id, m.frame_timestamp_seconds) for m in matches] == [(first, 3.0)]


def test_video_completion_records_playback_copy(store, settings):
    aid, _ = enqueue(settings, "video")
    job = store.claim()
    key = f"assets/{aid}/playback/web.mp4"
    store.complete(job, [VectorRecord(aid, VECTOR, "test-model", 0.0)], playback_key=key)
    with connection(settings) as conn:
        assert conn.execute(
            "SELECT processing_status, playback_key FROM assets WHERE id=%s", (aid,)
        ).fetchone() == ("READY", key)


def test_hybrid_fuses_before_limit_and_respects_scope_and_latest_metadata(store, settings):
    visual, _ = enqueue(settings)
    textual, _ = enqueue(settings, "video")
    excluded, _ = enqueue(settings)
    settings = settings.model_copy(update={"embedding_model": "embeddinggemma2"})
    version = embedding_version(GEMMA_ID)
    axis_x = (1.0,) + (0.0,) * 767
    axis_y = (0.0, 1.0) + (0.0,) * 766
    with connection(settings) as conn:
        conn.execute("UPDATE assets SET processing_status='READY',title='Lion'")
        conn.execute("UPDATE assets SET species='Zebras' WHERE id=%s", (textual,))
        conn.execute("UPDATE assets SET description='Zebra' WHERE id=%s", (excluded,))
    repo = PgVectorRepository(settings)
    repo.replace(visual, version, [VectorRecord(visual, axis_x, version)])
    vector = (0.8, 0.6) + (0.0,) * 766
    repo.replace(textual, version, [
        VectorRecord(textual, axis_y, version, 0.0),
        VectorRecord(textual, vector, version, 3.0),
    ])
    repo.replace(excluded, version, [VectorRecord(excluded, axis_x, version)])
    scope = [visual, textual]
    encoded = []

    def encode_document(text):
        encoded.append(text)
        return axis_x if "zebra" in text.lower() else axis_y

    repo.refresh_metadata_vectors(version, encode_document, scope)
    assert len(encoded) == 2
    repo.refresh_metadata_vectors(version, encode_document, scope)
    assert len(encoded) == 2  # Unchanged metadata reuses its cached embedding.
    matches = repo.search_hybrid(axis_x, version, "a zebra", 1, scope)
    assert len(matches) == 1
    assert matches[0].asset_id == textual
    assert matches[0].score == pytest.approx(0.84)
    assert matches[0].frame_timestamp_seconds == 3.0
    assert repo.search_hybrid(axis_x, version, "zebra", 10, []) == []
    assert repo.search_hybrid(axis_x, "other-model", "zebra", 10, scope) == []
    with connection(settings) as conn:
        conn.execute("UPDATE assets SET description='A zebra' WHERE id=%s", (visual,))
    # Old text vectors must never contribute to a score after a metadata edit.
    assert repo.search_hybrid(axis_x, version, "zebra", 1, scope)[0].asset_id == textual
    repo.refresh_metadata_vectors(version, encode_document, scope)
    assert len(encoded) == 3
    assert repo.search_hybrid(axis_x, version, "zebras", 1, scope)[0].asset_id == visual
    with connection(settings) as conn:
        conn.execute("UPDATE assets SET processing_status='PROCESSING' WHERE id=%s", (visual,))
    assert all(m.asset_id != visual for m in repo.search_hybrid(
        axis_x, version, "zebra", 10, scope
    ))


def test_generated_description_is_atomic_and_preserves_user_description(store, settings):
    from mediamesh_ml.contracts import GeneratedDescription

    aid, _ = enqueue(settings)
    with connection(settings) as conn:
        conn.execute("UPDATE assets SET description='User-written text' WHERE id=%s", (aid,))
    job = store.claim()
    caption = GeneratedDescription("A tiger stands on grass.", "test-caption-model")
    with pytest.raises(ValueError):
        store.complete(job, [VectorRecord(aid, (0.0,) * 512, "test")],
                       generated_description=caption)
    with connection(settings) as conn:
        row = conn.execute(
            "SELECT generated_description FROM assets WHERE id=%s", (aid,)
        ).fetchone()
        assert row == (None,)
    store.complete(job, [VectorRecord(aid, VECTOR, "test")], generated_description=caption)
    with connection(settings) as conn:
        row = conn.execute(
            "SELECT description,generated_description,description_model,description_generated_at "
            "FROM assets WHERE id=%s", (aid,),
        ).fetchone()
    assert row[:3] == ("User-written text", caption.text, caption.model)
    assert row[3] is not None
    with pytest.raises(StaleClaim):
        store.complete(job, [VectorRecord(aid, VECTOR, "test")],
                       generated_description=GeneratedDescription("Wrong", "stale"))


def test_upload_worker_retries_caption_failure_then_commits_description(store, settings, tmp_path):
    from PIL import Image

    from mediamesh_ml.contracts import GeneratedDescription, ModelIdentity
    from mediamesh_ml.indexing import IndexingService
    from mediamesh_ml.media import LocalMediaSource
    from mediamesh_ml.worker import Worker

    aid, jid = enqueue(settings)
    path = tmp_path / "assets" / str(aid)
    path.parent.mkdir()
    Image.new("RGB", (32, 32), "green").save(path, format="PNG")

    class Engine:
        identity = ModelIdentity("test", "r", 512)

        def encode_images(self, paths):
            return [VECTOR]

    class Describer:
        fail = True

        def describe(self, paths):
            assert paths[0].exists()
            if self.fail:
                raise OSError("Caption service temporarily unavailable")
            return GeneratedDescription("A green square.", "test-caption-model")

    describer = Describer()
    worker = Worker(store, IndexingService(
        Engine(), LocalMediaSource(tmp_path), PgVectorRepository(settings), describer=describer
    ), settings)
    assert worker.run_once()
    assert store.status(jid)["status"] == "PENDING"
    describer.fail = False
    assert worker.run_once()
    assert store.status(jid)["status"] == "SUCCEEDED"
    with connection(settings) as conn:
        row = conn.execute(
            "SELECT generated_description FROM assets WHERE id=%s", (aid,)
        ).fetchone()
    assert row == ("A green square.",)


def test_caption_backfill_is_resumable_and_preserves_authored_and_concurrent_text(store, settings):
    from unittest.mock import patch

    from mediamesh_ml.captions import backfill
    from mediamesh_ml.contracts import GeneratedDescription
    from mediamesh_ml.indexing import IndexingService

    fresh, _ = enqueue(settings)
    existing, _ = enqueue(settings)
    concurrent, _ = enqueue(settings)
    settings = settings.model_copy(update={
        "embedding_model": "embeddinggemma2",
        "azure_emulator_endpoint": "http://azurite:10000/devstoreaccount1",
    })
    with connection(settings) as conn:
        conn.execute("UPDATE assets SET processing_status='READY',description='Authored text'")
        conn.execute(
            "UPDATE assets SET generated_description='Keep existing' WHERE id=%s", (existing,)
        )

    class Engine:
        model_version = embedding_version(GEMMA_ID)

        def load(self):
            pass

        def encode_document(self, text):
            return (1.0,) + (0.0,) * 767

    def describe(reference, media_type):
        if reference == f"assets/{concurrent}":
            with connection(settings) as conn:
                conn.execute(
                    "UPDATE assets SET generated_description='Concurrent caption' WHERE id=%s",
                    (concurrent,),
                )
        return GeneratedDescription("A zebra on grass.", "test-caption-model")

    with patch("mediamesh_ml.embeddings.create_engine", return_value=Engine()):
        with patch.object(IndexingService, "prepare_description", side_effect=describe) as generate:
            assert backfill(settings) == 0
            assert generate.call_count == 2
        with patch.object(IndexingService, "prepare_description") as generate:
            assert backfill(settings) == 0
            generate.assert_not_called()
    with connection(settings) as conn:
        rows = dict(conn.execute("SELECT id,generated_description FROM assets").fetchall())
        authored = conn.execute(
            "SELECT count(*) FROM assets WHERE description='Authored text'"
        ).fetchone()[0]
        assert authored == 3
        assert conn.execute("SELECT count(*) FROM asset_vectors").fetchone()[0] == 0
    assert rows == {
        fresh: "A zebra on grass.", existing: "Keep existing", concurrent: "Concurrent caption"
    }


def test_demo_enrichment_generates_only_selected_missing_data(store, settings, tmp_path):
    from contextlib import nullcontext
    from unittest.mock import patch

    from PIL import Image

    from mediamesh_ml.contracts import GeneratedDescription
    from mediamesh_ml.seed_enrich import enrich

    selected, _ = enqueue(settings)
    unrelated, _ = enqueue(settings)
    settings = settings.model_copy(update={"embedding_model": "embeddinggemma2"})
    with connection(settings) as conn:
        conn.execute("UPDATE assets SET processing_status='READY',description='Manual description'")
    image = tmp_path / "demo.png"
    Image.new("RGB", (32, 32), "green").save(image)
    vector = (1.0,) + (0.0,) * 767

    class Engine:
        identity = GEMMA_ID
        model_version = embedding_version(GEMMA_ID)

        def load(self):
            pass

        def encode_images(self, paths):
            assert paths == [image]
            return [vector]

        def encode_document(self, text):
            assert "A green square" in text
            return vector

    class Source:
        def __init__(self, settings):
            pass

        def materialize(self, reference):
            assert reference == f"assets/{selected}"
            return nullcontext(image)

    caption = GeneratedDescription("A green square.", "test-caption-model")
    with patch("mediamesh_ml.embeddings.create_engine", return_value=Engine()), \
         patch("mediamesh_ml.reindex.create_engine", return_value=Engine()), \
         patch("mediamesh_ml.seed_enrich.create_engine", return_value=Engine()), \
         patch("mediamesh_ml.reindex.AzureBlobMediaSource", Source), \
         patch("mediamesh_ml.media.AzureBlobMediaSource", Source), \
         patch("mediamesh_ml.captions.VisualDescriber.describe", return_value=caption) as describe:
        enrich(settings, [selected])
        enrich(settings, [selected])
        assert describe.call_count == 1
    with connection(settings) as conn:
        assert conn.execute("SELECT count(*) FROM asset_vectors").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM asset_metadata_vectors").fetchone()[0] == 1
        rows = dict(conn.execute("SELECT id,generated_description FROM assets").fetchall())
    assert rows == {selected: caption.text, unrelated: None}
