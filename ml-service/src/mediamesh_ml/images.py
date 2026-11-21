"""Bounded image preparation shared by evaluation and the future indexer."""

import warnings
from pathlib import Path

from PIL import Image, ImageOps


def prepare_image(path: Path, *, max_pixels: int = 20_000_000) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as source:
            if source.width * source.height > max_pixels:
                raise ValueError("Image exceeds pixel limit")
            source.load()  # Force decoding while the underlying file is open.
            return ImageOps.exif_transpose(source).convert("RGB")
