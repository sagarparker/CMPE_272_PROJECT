from pathlib import Path

import pytest
from PIL import Image, UnidentifiedImageError

from mediamesh_ml.images import prepare_image


def test_grayscale_and_exif_are_prepared(tmp_path):
    path = tmp_path / "rotated.jpg"
    image = Image.new("L", (10, 20))
    exif = Image.Exif()
    exif[274] = 6  # 90 degree clockwise orientation.
    image.save(path, exif=exif)
    with prepare_image(path) as prepared:
        assert prepared.mode == "RGB"
        assert prepared.size == (20, 10)
        path.unlink()  # Prepared pixels do not depend on an open source file.
        assert prepared.getpixel((0, 0)) == (0, 0, 0)


def test_oversize_and_corrupt_images_fail(tmp_path):
    path = tmp_path / "image.png"
    Image.new("RGB", (20, 20)).save(path)
    with pytest.raises(ValueError, match="pixel limit"):
        prepare_image(path, max_pixels=100)
    path.write_bytes(b"not an image")
    with pytest.raises(UnidentifiedImageError):
        prepare_image(Path(path))
