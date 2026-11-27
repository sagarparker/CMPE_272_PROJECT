import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.video import VideoSampler, sampling_interval


def test_sampling_interval_is_bounded():
    assert sampling_interval(60, 8) == 7.5
    for duration in [0, -1, float("inf"), float("nan")]:
        with pytest.raises(ValueError):
            sampling_interval(duration, 8)


@pytest.mark.parametrize(
    "payload",
    [
        {"streams": []},
        {"streams": [{"width": 10, "height": 10}], "format": {"duration": "N/A"}},
        {"streams": [{"width": 10, "height": 10, "duration": "inf"}]},
        {"streams": [{"width": 10, "height": 10, "duration": "181"}]},
        {"streams": [{"width": 10000, "height": 10000, "duration": "2"}]},
    ],
)
def test_invalid_probe_metadata_is_rejected(monkeypatch, payload):
    monkeypatch.setattr(
        "mediamesh_ml.video.run_tool",
        lambda *a, **k: CompletedProcess([], 0, json.dumps(payload), ""),
    )
    with pytest.raises(ValueError):
        VideoSampler(Settings()).probe(Path("/video.webm"))


@pytest.fixture
def short_video(tmp_path):
    import subprocess

    path = tmp_path / "test.mp4"
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
    return path


def test_real_ffmpeg_sampling_timestamps_and_cleanup(short_video, tmp_path):
    temp = tmp_path / "frames"
    temp.mkdir()
    sampler = VideoSampler(Settings(video_max_frames=4, video_temp_root=temp))
    assert sampler.probe(short_video).duration_seconds == pytest.approx(4)
    with sampler.extract(short_video) as frames:
        assert len(frames) == 4
        assert [f.timestamp_seconds for f in frames] == pytest.approx([0, 1, 2, 3])
        paths = [f.path for f in frames]
        assert all(p.is_file() for p in paths)
    assert all(not p.exists() for p in paths)
    assert not list(temp.iterdir())


def test_non_frame_aligned_sampling_uses_actual_decoded_pts(short_video):
    sampler = VideoSampler(Settings(video_max_frames=3))
    with sampler.extract(short_video) as frames:
        # Targets are 0, 1.333..., 2.666...; real 4-fps frames are later.
        assert [f.timestamp_seconds for f in frames] == pytest.approx([0, 1.5, 2.75])


def test_corrupt_and_overlong_video_fail(short_video, tmp_path):
    corrupt = tmp_path / "bad.mp4"
    corrupt.write_bytes(b"not video")
    with pytest.raises(ValueError, match="decoded"):
        VideoSampler(Settings()).probe(corrupt)
    with pytest.raises(ValueError, match="duration"):
        VideoSampler(Settings(video_max_duration_seconds=1)).probe(short_video)


def test_extraction_failure_cleans_temporary_directory(monkeypatch, short_video, tmp_path):
    from mediamesh_ml.video import VideoInfo

    temp = tmp_path / "temporary"
    temp.mkdir()
    sampler = VideoSampler(Settings(video_temp_root=temp))
    monkeypatch.setattr(sampler, "probe", lambda *a, **k: VideoInfo(4, 160, 90))

    def fail(*args, **kwargs):
        # Simulate a decoder failure after it has created partial output.
        directory = next(temp.iterdir())
        (directory / "frame-001.jpg").write_bytes(b"partial")
        raise ValueError("Decoder failed")

    monkeypatch.setattr("mediamesh_ml.video.run_tool", fail)
    with pytest.raises(ValueError, match="Decoder"), sampler.extract(short_video):
        pytest.fail("Unexpected success")
    assert list(temp.iterdir()) == []


def test_tool_timeout_is_reported_without_leaking_subprocess_details(monkeypatch):
    import subprocess

    from mediamesh_ml.video import run_tool

    def expire(*args, **kwargs):
        raise subprocess.TimeoutExpired("sensitive path", 1)

    monkeypatch.setattr(subprocess, "run", expire)
    with pytest.raises(ValueError, match="timed out") as error:
        run_tool(["ffmpeg"], 1)
    assert "sensitive" not in str(error.value)
