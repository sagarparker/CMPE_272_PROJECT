from uuid import uuid4

import pytest
from PIL import Image

from mediamesh_ml.contracts import ModelIdentity
from mediamesh_ml.images import prepare_image
from mediamesh_ml.indexing import IndexingService
from mediamesh_ml.media import LocalMediaSource


class Engine:
    identity = ModelIdentity("test-model", "revision", 512)

    def encode_images(self, paths):
        for path in paths:
            with prepare_image(path):
                pass
        return [(1.0,) + (0.0,) * 511 for _ in paths]


class Store:
    def __init__(self):
        self.records = []

    def replace(self, asset_id, model_version, records):
        self.records = list(records)


def test_image_pipeline_persists_one_null_timestamp(tmp_path):
    Image.new("RGB", (32, 32)).save(tmp_path / "image.png")
    store = Store()
    service = IndexingService(Engine(), LocalMediaSource(tmp_path), store)
    aid = uuid4()
    rows = service.index_image(aid, "image.png")
    assert store.records == rows
    assert rows[0].asset_id == aid
    assert rows[0].frame_timestamp_seconds is None


def test_failed_decode_preserves_previous_records(tmp_path):
    Image.new("RGB", (32, 32)).save(tmp_path / "image.png")
    store = Store()
    service = IndexingService(Engine(), LocalMediaSource(tmp_path), store)
    aid = uuid4()
    service.index_image(aid, "image.png")
    before = list(store.records)
    (tmp_path / "image.png").write_bytes(b"corrupt")
    with pytest.raises(OSError):
        service.index_image(aid, "image.png")
    assert store.records == before


def test_video_preparation_cleans_up_even_if_encoding_fails(tmp_path):
    from contextlib import contextmanager

    from mediamesh_ml.video import VideoFrame

    (tmp_path / "video.webm").write_bytes(b"test placeholder")
    frame_path = tmp_path / "temporary.png"

    class Sampler:
        @contextmanager
        def extract(self, path):
            Image.new("RGB", (16, 16)).save(frame_path)
            try:
                yield [VideoFrame(frame_path, 0.0)]
            finally:
                frame_path.unlink()

    class BrokenEngine(Engine):
        def encode_images(self, paths):
            raise RuntimeError("Inference failed")

    store = Store()
    store.records = ["previous vectors"]
    service = IndexingService(BrokenEngine(), LocalMediaSource(tmp_path), store, Sampler())
    with pytest.raises(RuntimeError, match="Inference"):
        service.index_video(uuid4(), "video.webm")
    assert store.records == ["previous vectors"]
    assert not frame_path.exists()
