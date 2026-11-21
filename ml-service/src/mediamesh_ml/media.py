"""Local media access restricted to a configured directory."""

from contextlib import contextmanager
from pathlib import Path


class LocalMediaSource:
    def __init__(self, root: Path, *, max_bytes: int = 100_000_000):
        self.root = root.resolve(strict=True)
        self.max_bytes = max_bytes

    @contextmanager
    def materialize(self, reference: str):
        # URLs, devices, and paths outside the media mount are not local assets.
        if not reference or "://" in reference or "\x00" in reference:
            raise ValueError("Expected a local media path")
        path = Path(reference)
        path = (
            (self.root / path).resolve(strict=True)
            if not path.is_absolute()
            else path.resolve(strict=True)
        )
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError("Media must be a regular file inside the configured media root")
        size = path.stat().st_size
        if size <= 0 or size > self.max_bytes:
            raise ValueError("Media file is empty or exceeds the size limit")
        yield path
