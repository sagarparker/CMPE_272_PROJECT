"""Browser-safe playback copies of uploaded videos.

Phones record HEVC, 10-bit HDR/Dolby Vision, 4K60 and rotation flags that many
browsers decode badly or not at all. The worker publishes an upright H.264/AAC
MP4 (SDR, at most 1080p/30 fps, fast start) next to the untouched original.
Previews play the copy; downloads still return the original.
"""

import argparse
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from mediamesh_ml.config import Settings
from mediamesh_ml.video import INPUT_OPTIONS, VideoSampler, run_tool

logger = logging.getLogger(__name__)

# HDR (PQ or HLG) to SDR BT.709. Scale first so tone mapping runs at output size.
TONEMAP = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"
)


def playback_key(reference: str) -> str:
    head, separator, _ = reference.rpartition("/source/")
    if not separator or not head.startswith("assets/") or "\x00" in reference:
        raise ValueError("Expected a catalog source key")
    return head + "/playback/web.mp4"


class PlaybackPublisher:
    def __init__(self, settings: Settings, blobs, sampler: VideoSampler | None = None):
        self.settings = settings
        self.blobs = blobs
        self.sampler = sampler or VideoSampler(settings)

    def command(self, source: Path, output: Path, hdr: bool) -> list[str]:
        edge = self.settings.video_playback_max_edge
        scale = (
            f"scale=w='min({edge},iw)':h='min({edge},ih)':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2,"
        )
        return [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-threads", "2", *INPUT_OPTIONS, "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1", "-dn", "-sn",
            "-vf", scale + (TONEMAP if hdr else "") + "format=yuv420p",
            "-fpsmax", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",
            "-movflags", "+faststart", str(output),
        ]  # fmt: skip

    def publish(self, source: Path, reference: str) -> str:
        """Encode, verify and upload the playback copy; return its blob key."""
        key = playback_key(reference)
        info = self.sampler.probe(source)
        with TemporaryDirectory(
            prefix="mediamesh-playback-", dir=self.settings.video_temp_root
        ) as tmp:
            output = Path(tmp) / "web.mp4"
            run_tool(
                self.command(source, output, info.hdr),
                self.settings.video_playback_timeout_seconds,
            )
            result = self.sampler.probe(output)
            if result.hdr or abs(result.duration_seconds - info.duration_seconds) > 1:
                raise ValueError("Playback copy failed verification")
            self.blobs.upload(key, output, "video/mp4")
        return key


def backfill(settings: Settings, *, asset_id=None) -> int:
    """Create playback copies for READY videos that do not have one yet."""
    from mediamesh_ml.database import connection
    from mediamesh_ml.media import AzureBlobMediaSource

    if not settings.production_mode:
        raise ValueError("Backfill runs against the production catalog only")
    blobs = AzureBlobMediaSource(settings)
    publisher = PlaybackPublisher(settings, blobs)
    with connection(settings) as conn:
        rows = conn.execute(
            "SELECT id, s3_key FROM assets WHERE media_type='video' AND processing_status='READY' "
            "AND playback_key IS NULL AND (%s::uuid IS NULL OR id=%s::uuid) ORDER BY created_at",
            (asset_id, asset_id),
        ).fetchall()
    done = 0
    for aid, reference in rows:
        try:
            with blobs.materialize(reference) as path:
                key = publisher.publish(path, reference)
        except Exception as error:
            logger.warning("Playback copy failed for asset %s: %s", aid, type(error).__name__)
            continue
        with connection(settings) as conn:
            conn.execute(
                "UPDATE assets SET playback_key=%s WHERE id=%s AND playback_key IS NULL",
                (key, aid),
            )
        logger.info("Published playback copy for asset %s", aid)
        done += 1
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backfill"])
    parser.add_argument("--asset-id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(f"Published {backfill(Settings(), asset_id=args.asset_id)} playback copies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
