"""Bounded video inspection and uniform decoded-frame sampling."""

import json
import math
import re
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from mediamesh_ml.config import Settings

# Restrict demuxers as well as protocols; do not accept playlists/remote references.
INPUT_OPTIONS = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm"]


@dataclass(frozen=True)
class VideoInfo:
    duration_seconds: float
    width: int
    height: int


@dataclass(frozen=True)
class VideoFrame:
    path: Path
    timestamp_seconds: float


def sampling_interval(duration_seconds: float, max_frames: int) -> float:
    if not math.isfinite(duration_seconds) or duration_seconds <= 0 or max_frames < 1:
        raise ValueError("Expected positive duration and frame count")
    return duration_seconds / max_frames


def run_tool(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    if timeout <= 0:
        raise ValueError("Video processing timed out")
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Video processing timed out") from None
    except subprocess.CalledProcessError:
        raise ValueError("Video could not be decoded by FFmpeg/ffprobe") from None


class VideoSampler:
    def __init__(self, settings: Settings):
        self.settings = settings

    def probe(self, path: Path, *, timeout: float | None = None) -> VideoInfo:
        response = run_tool(
            [
                "ffprobe",
                "-v",
                "error",
                *INPUT_OPTIONS,
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            timeout if timeout is not None else self.settings.video_timeout_seconds,
        )
        try:
            data = json.loads(response.stdout)
            stream = data["streams"][0]
            duration = stream.get("duration")
            if duration in {None, "N/A"}:
                duration = data.get("format", {}).get("duration")
            info = VideoInfo(float(duration), int(stream["width"]), int(stream["height"]))
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("Video must have a valid duration and video stream") from None
        if not math.isfinite(info.duration_seconds) or not (
            0 < info.duration_seconds <= self.settings.video_max_duration_seconds
        ):
            raise ValueError("Video duration exceeds supported limits")
        if (
            info.width <= 0
            or info.height <= 0
            or (info.width * info.height > self.settings.video_max_pixels)
        ):
            raise ValueError("Video dimensions exceed supported limits")
        return info

    @contextmanager
    def extract(self, path: Path):
        deadline = time.monotonic() + self.settings.video_timeout_seconds
        info = self.probe(path, timeout=deadline - time.monotonic())
        interval = sampling_interval(info.duration_seconds, self.settings.video_max_frames)
        with TemporaryDirectory(
            prefix="mediamesh-frames-", dir=self.settings.video_temp_root
        ) as tmp:
            output = Path(tmp)
            # Normalize actual decoded PTS to the first video frame. showinfo records
            # timestamps after selection, before the output encoder changes timing.
            filters = (
                "setpts=PTS-STARTPTS,"
                f"select='gte(t,selected_n*{interval:.12f})',"
                "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease,"
                "showinfo"
            )
            result = run_tool(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "info",
                    "-xerror",
                    "-threads",
                    "2",
                    "-filter_threads",
                    "1",
                    *INPUT_OPTIONS,
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-an",
                    "-sn",
                    "-dn",
                    "-vf",
                    filters,
                    "-fps_mode",
                    "vfr",
                    "-frames:v",
                    str(self.settings.video_max_frames),
                    "-q:v",
                    "3",
                    str(output / "frame-%03d.jpg"),
                ],
                deadline - time.monotonic(),
            )
            timestamps = [
                float(value)
                for value in re.findall(
                    r"\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:\s*([0-9.eE+-]+)", result.stderr
                )
            ]
            paths = sorted(output.glob("frame-*.jpg"))
            if (
                not paths
                or len(paths) > self.settings.video_max_frames
                or len(timestamps) < len(paths)
            ):
                raise ValueError("Video extraction returned no frames or invalid timestamps")
            # FFmpeg may filter one extra frame before enforcing the output limit.
            timestamps = timestamps[: len(paths)]
            if any(not math.isfinite(t) or t < 0 or t >= info.duration_seconds for t in timestamps):
                raise ValueError("Decoded frame timestamp is outside the video duration")
            if timestamps != sorted(set(timestamps)):
                raise ValueError("Decoded frame timestamps must be unique and increasing")
            yield [VideoFrame(p, t) for p, t in zip(paths, timestamps, strict=True)]
