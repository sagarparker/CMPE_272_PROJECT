import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.indexing import IndexingService
from mediamesh_ml.media import AzureBlobMediaSource
from mediamesh_ml.playback import PlaybackPublisher, playback_key
from mediamesh_ml.video import VideoSampler


def test_playback_key_sits_beside_the_source_and_rejects_other_keys():
    assert playback_key("assets/o/a/source/IMG_1.MOV") == "assets/o/a/playback/web.mp4"
    for bad in ["assets/o/a/IMG.MOV", "other/o/a/source/x.mov", "assets/source"]:
        with pytest.raises(ValueError):
            playback_key(bad)


def test_upload_never_overwrites_a_source_object(tmp_path):
    client = Mock()
    media = AzureBlobMediaSource(Settings(), client=client)
    copy = tmp_path / "web.mp4"
    copy.write_bytes(b"mp4")
    with pytest.raises(ValueError):
        media.upload("assets/o/a/source/x.mov", copy, "video/mp4")
    media.upload("assets/o/a/playback/web.mp4", copy, "video/mp4")
    client.get_blob_client.assert_called_once_with(
        container="mediamesh", blob="assets/o/a/playback/web.mp4"
    )
    kwargs = client.get_blob_client.return_value.upload_blob.call_args.kwargs
    assert kwargs["overwrite"] is True
    assert kwargs["content_settings"].content_type == "video/mp4"


def test_tone_mapping_only_for_hdr_sources(tmp_path):
    publisher = PlaybackPublisher(Settings(), Mock())
    sdr = " ".join(publisher.command(tmp_path / "in", tmp_path / "out", hdr=False))
    hdr = " ".join(publisher.command(tmp_path / "in", tmp_path / "out", hdr=True))
    assert "tonemap" not in sdr and "tonemap" in hdr
    for expected in [
        "libx264",
        "+faststart",
        "-fpsmax 30",
        "yuv420p",
        "-map_metadata -1",
    ]:
        assert expected in sdr


@pytest.fixture
def phone_video(tmp_path):
    """10-bit HLG HEVC-style source, recorded sideways with a rotation flag."""
    encoded, path = tmp_path / "encoded.mov", tmp_path / "phone.mov"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=60",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p10le",
            "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
            "-c:a", "aac", str(encoded),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    # FFmpeg 5.1 writes the display-matrix rotation flag only when stream copying.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(encoded), "-c", "copy",
         "-metadata:s:v:0", "rotate=90", str(path)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    encoded.unlink()
    return path


def test_real_hdr_rotated_source_becomes_upright_sdr_h264(phone_video, tmp_path):
    uploaded = {}

    class Blobs:
        def upload(self, key, path, content_type):
            uploaded.update(key=key, type=content_type, bytes=path.read_bytes())

    settings = Settings(video_temp_root=tmp_path)
    sampler = VideoSampler(settings)
    assert sampler.probe(phone_video).hdr
    key = PlaybackPublisher(settings, Blobs(), sampler).publish(
        phone_video, "assets/o/a/source/phone.mov"
    )
    assert key == uploaded["key"] == "assets/o/a/playback/web.mp4"
    assert uploaded["type"] == "video/mp4"
    output = tmp_path / "check.mp4"
    output.write_bytes(uploaded["bytes"])
    data = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)]
        )
    )
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p"
    assert video["color_transfer"] == "bt709"
    assert (video["width"], video["height"]) == (180, 320)  # rotation applied
    assert video["r_frame_rate"] == "30/1"
    assert not [d for d in video.get("side_data_list", []) if d.get("rotation")]
    assert any(s["codec_type"] == "audio" for s in data["streams"])
    # Directory listing order is filesystem-dependent; only the two expected files remain.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["check.mp4", "phone.mov"]


def test_playback_failure_keeps_search_vectors(tmp_path):
    frames = [SimpleNamespace(path=tmp_path / "f.jpg", timestamp_seconds=0.0)]

    class Sampler:
        def extract(self, path):
            from contextlib import nullcontext

            return nullcontext(frames)

    class Source:
        def materialize(self, reference):
            from contextlib import nullcontext

            return nullcontext(tmp_path / "in.mov")

    engine = Mock()
    engine.identity = SimpleNamespace(name="m", revision="r", dimensions=512)
    engine.encode_images.return_value = [(1.0,) + (0.0,) * 511]
    playback = Mock()
    playback.publish.side_effect = ValueError("encoder failed")
    service = IndexingService(engine, Source(), Mock(), Sampler(), playback)
    records, key = service.prepare_video_job(uuid4(), "assets/o/a/source/in.mov")
    assert len(records) == 1 and key is None
