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
