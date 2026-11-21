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
