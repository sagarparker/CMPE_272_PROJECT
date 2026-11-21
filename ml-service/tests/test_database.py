"""Destructive fixtures are restricted to the explicit ephemeral test database."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import VectorRecord
from mediamesh_ml.database import connection, database_status
from mediamesh_ml.migrate import apply_migrations
from mediamesh_ml.vectors import PgVectorRepository, replace_in_transaction, vector_literal

pytestmark = pytest.mark.database
MIGRATIONS = Path(os.getenv("ML_MIGRATIONS_DIRECTORY", "/app/migrations"))
AXIS_X = (1.0,) + (0.0,) * 511
AXIS_Y = (0.0, 1.0) + (0.0,) * 510


@pytest.fixture(scope="module")
def settings():
    url = os.getenv("ML_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ML_TEST_DATABASE_URL to run isolated database tests")
    settings = Settings(database_url=url)
    with connection(settings) as conn:
        if conn.info.dbname != "mediamesh_test" or conn.info.host != "postgres-test":
            pytest.fail("Destructive tests require postgres-test/mediamesh_test")
        conn.execute("DROP TABLE IF EXISTS asset_vectors, ml_schema_migrations, assets CASCADE")
    apply_migrations(settings, MIGRATIONS, fixture=Path("dev/bootstrap_assets.sql"))
    return settings


@pytest.fixture
def store(settings):
    with connection(settings) as conn:
        conn.execute("TRUNCATE assets CASCADE")
    return PgVectorRepository(settings)


def asset(settings, value=None):
    value = value or uuid4()
    with connection(settings) as conn:
        conn.execute("INSERT INTO assets(id) VALUES (%s)", (value,))
    return value


def record(asset_id, vector=AXIS_X, version="model-a", timestamp=None):
    return VectorRecord(asset_id, vector, version, timestamp)


def count(settings):
    with connection(settings) as conn:
        return conn.execute("SELECT count(*) FROM asset_vectors").fetchone()[0]


def test_migrations_are_repeatable_and_detect_changed_history(settings, tmp_path):
    apply_migrations(settings, MIGRATIONS)
    assert database_status(settings) == {"vector_extension": True, "vector_table": True}
    source = next(MIGRATIONS.glob("V300__*.sql"))
    (tmp_path / source.name).write_text(source.read_text() + "\n-- altered\n")
    with pytest.raises(ValueError, match="changed"):
        apply_migrations(settings, tmp_path)


def test_empty_search_and_repeat_replacement(store, settings):
    assert store.search(AXIS_X, "model-a", 5) == []
    aid = asset(settings)
    for _ in range(2):
        store.replace(aid, "model-a", [record(aid)])
    assert count(settings) == 1
    matches = store.search(AXIS_X, "model-a", 5)
    assert matches[0].asset_id == aid
    assert matches[0].score == pytest.approx(1)
    assert matches[0].frame_timestamp_seconds is None


def test_ranking_and_model_isolation(store, settings):
    a = asset(settings, UUID(int=1))
    b = asset(settings, UUID(int=2))
    store.replace(a, "model-a", [record(a, AXIS_Y)])
    store.replace(b, "model-a", [record(b)])
    store.replace(a, "other-model", [record(a, version="other-model")])
    assert [m.asset_id for m in store.search(AXIS_X, "model-a", 5)] == [b, a]
    assert [m.asset_id for m in store.search(AXIS_X, "other-model", 5)] == [a]
    assert store.search(AXIS_X, "absent-version", 5) == []
    store.replace(a, "other-model", [])
    assert count(settings) == 2  # Clearing one version preserves the other.


def test_video_timestamps_replace_outdated_frames(store, settings):
    aid = asset(settings)
    store.replace(aid, "model-a", [record(aid, timestamp=t) for t in [0.0, 4.5, 9.0]])
    store.replace(aid, "model-a", [record(aid, timestamp=2.25)])
    matches = store.search(AXIS_X, "model-a", 10)
    assert len(matches) == 1
    assert matches[0].frame_timestamp_seconds == 2.25


def test_failed_transaction_preserves_old_set(store, settings):
    aid = asset(settings)
    store.replace(aid, "model-a", [record(aid)])
    with pytest.raises(RuntimeError):
        with connection(settings) as conn:
            replace_in_transaction(conn, aid, "model-a", [record(aid, AXIS_Y)])
            raise RuntimeError("Simulated failure before job completion")
    assert store.search(AXIS_X, "model-a", 1)[0].score == pytest.approx(1)


def test_database_constraints_are_enforced_directly(store, settings):
    aid = asset(settings)
    store.replace(aid, "model-a", [record(aid)])
    cases = [
        (aid, None, vector_literal(AXIS_X), psycopg.errors.UniqueViolation),
        (aid, -1, vector_literal(AXIS_X), psycopg.errors.CheckViolation),
        (aid, float("inf"), vector_literal(AXIS_X), psycopg.errors.CheckViolation),
        (aid, float("nan"), vector_literal(AXIS_X), psycopg.errors.CheckViolation),
        (aid, 1, "[1,0]", psycopg.errors.DataException),
        (aid, 1, "[" + ",".join(["0"] * 512) + "]", psycopg.errors.CheckViolation),
        (uuid4(), None, vector_literal(AXIS_X), psycopg.errors.ForeignKeyViolation),
    ]
    for asset_id, timestamp, embedding, error in cases:
        with pytest.raises(error), connection(settings) as conn:
            conn.execute(
                "INSERT INTO asset_vectors(asset_id, frame_timestamp_seconds, "
                "model_version, embedding) VALUES (%s, %s, 'model-a', %s::vector)",
                (asset_id, timestamp, embedding),
            )
    # A video at t=0 remains distinct from an image's null timestamp.
    with connection(settings) as conn:
        conn.execute(
            "INSERT INTO asset_vectors(asset_id, frame_timestamp_seconds, "
            "model_version, embedding) VALUES (%s, 0, 'model-a', %s::vector)",
            (aid, vector_literal(AXIS_X)),
        )
    assert count(settings) == 2


def test_concurrent_replacements_leave_one_complete_set(store, settings):
    aid = asset(settings)

    def replace(offset):
        store.replace(aid, "model-a", [record(aid, timestamp=offset + i) for i in range(4)])

    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(replace, [0, 10, 20]))
    timestamps = sorted(m.frame_timestamp_seconds for m in store.search(AXIS_X, "model-a", 10))
    assert len(timestamps) == 4
    assert timestamps == list(range(int(timestamps[0]), int(timestamps[0]) + 4))


def test_explicit_deletion_and_asset_cascade(store, settings):
    aid = asset(settings)
    store.replace(aid, "model-a", [record(aid)])
    store.delete(aid)
    assert count(settings) == 0
    store.replace(aid, "model-a", [record(aid)])
    with connection(settings) as conn:
        conn.execute("DELETE FROM assets WHERE id=%s", (aid,))
    assert count(settings) == 0


@pytest.mark.skipif(os.getenv("ML_RUN_MODEL_TESTS") != "1", reason="explicit real-model opt-in")
def test_real_clip_vectors_round_trip_through_postgres(store, settings):
    import json

    from mediamesh_ml.embeddings import ClipEngine

    manifest = json.loads(Path("evaluation/manifest.json").read_text())
    selected = [i for i in manifest["items"] if i["id"] in {"elephant-02", "lion-01"}]
    engine = ClipEngine(Settings(model_offline=True))
    vectors = engine.encode_images([Path("/data/media") / i["filename"] for i in selected])
    ids = []
    for vector in vectors:
        aid = asset(settings)
        ids.append(aid)
        store.replace(aid, engine.model_version, [record(aid, vector, engine.model_version)])
    matches = store.search(
        engine.encode_text("elephants drinking at a watering hole"), engine.model_version, 2
    )
    assert matches[0].asset_id == ids[0]  # Elephant ranks above lion.
    assert len(matches) == 2


@pytest.mark.skipif(os.getenv("ML_RUN_MODEL_TESTS") != "1", reason="explicit real-model opt-in")
def test_image_indexer_reindex_and_failed_decode_preserve_vectors(store, settings, tmp_path):
    from mediamesh_ml.embeddings import ClipEngine
    from mediamesh_ml.indexing import IndexingService
    from mediamesh_ml.media import LocalMediaSource

    path = tmp_path / "elephant.jpg"
    path.write_bytes(Path("/data/media/elephant-02.jpg").read_bytes())
    engine = ClipEngine(Settings(model_offline=True))
    service = IndexingService(engine, LocalMediaSource(tmp_path), store)
    aid = asset(settings)
    first = service.index_image(aid, "elephant.jpg")
    second = service.index_image(aid, "elephant.jpg")
    assert first == second
    assert count(settings) == 1
    path.write_bytes(b"corrupt")
    with pytest.raises(OSError):
        service.index_image(aid, "elephant.jpg")
    assert count(settings) == 1
    assert store.search(first[0].embedding, service.model_version, 1)[0].score == pytest.approx(1)


def test_video_indexer_replaces_frames_and_preserves_old_set_on_error(store, settings, tmp_path):
    import subprocess

    from mediamesh_ml.contracts import ModelIdentity
    from mediamesh_ml.indexing import IndexingService
    from mediamesh_ml.media import LocalMediaSource
    from mediamesh_ml.video import VideoSampler

    path = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=4",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )

    class Engine:
        identity = ModelIdentity("test-model", "revision", 512)

        def encode_images(self, paths):
            return [AXIS_X for _ in paths]

    config = Settings(video_max_frames=4, video_temp_root=tmp_path)
    sampler = VideoSampler(config)
    service = IndexingService(Engine(), LocalMediaSource(tmp_path), store, sampler)
    aid = asset(settings)
    first = service.index_video(aid, "clip.mp4")
    assert len(first) == count(settings) == 4
    assert all(row.frame_timestamp_seconds is not None for row in first)
    sampler.settings = Settings(video_max_frames=2, video_temp_root=tmp_path)
    service.index_video(aid, "clip.mp4")
    assert count(settings) == 2  # Replaces the old set, including obsolete timestamps.
    path.write_bytes(b"broken video")
    with pytest.raises(ValueError):
        service.index_video(aid, "clip.mp4")
    assert count(settings) == 2
    assert not list(tmp_path.glob("mediamesh-frames-*"))


@pytest.mark.skipif(os.getenv("ML_RUN_VIDEO_TESTS") != "1", reason="explicit wildlife-video opt-in")
def test_real_wildlife_video_text_search_returns_asset_and_timestamp(store, settings):
    from mediamesh_ml.embeddings import ClipEngine
    from mediamesh_ml.indexing import IndexingService
    from mediamesh_ml.media import LocalMediaSource
    from mediamesh_ml.video import VideoSampler

    config = Settings(model_offline=True, video_max_frames=4)
    engine = ClipEngine(config)
    sampler = VideoSampler(config)
    service = IndexingService(engine, LocalMediaSource(Path("/data/media")), store, sampler)
    ids = {}
    durations = {}
    for subject in ["bison", "bear"]:
        ids[subject] = asset(settings)
        path = Path("/data/media") / f"video-{subject}.mp4"
        durations[subject] = sampler.probe(path).duration_seconds
        rows = service.index_video(ids[subject], path.name)
        assert len(rows) == 4
    assert count(settings) == 8
    for subject, query in [
        ("bison", "a herd of bison grazing in a green valley"),
        ("bear", "a bear walking through snow"),
    ]:
        match = store.search(engine.encode_text(query), service.model_version, 1)[0]
        assert match.asset_id == ids[subject]
        assert 0 <= match.frame_timestamp_seconds < durations[subject]


def test_asset_ranking_deduplicates_before_limit_and_breaks_ties(store, settings):
    video = asset(settings, UUID(int=1))
    image = asset(settings, UUID(int=2))
    other = asset(settings, UUID(int=3))
    store.replace(video, "model-a", [record(video, timestamp=i) for i in range(8)])
    store.replace(image, "model-a", [record(image, (0.8, 0.6) + (0.0,) * 510)])
    store.replace(other, "model-a", [record(other, AXIS_Y)])
    matches = store.search_assets(AXIS_X, "model-a", 3)
    assert [m.asset_id for m in matches] == [video, image, other]
    assert matches[0].frame_timestamp_seconds == 0
    assert matches[1].frame_timestamp_seconds is None
    assert [m.score for m in matches] == pytest.approx([1, 0.8, 0])
    store.replace(image, "model-a", [record(image)])
    assert [m.asset_id for m in store.search_assets(AXIS_X, "model-a", 2)] == [video, image]
    assert store.is_ready()
