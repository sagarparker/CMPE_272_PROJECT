import pytest
from PIL import Image

from mediamesh_ml.images import prepare_image
from mediamesh_ml.media import LocalMediaSource


def test_local_media_rejects_escape_symlink_and_url(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    (root / "link.jpg").symlink_to(outside)
    source = LocalMediaSource(root)
    for reference in ["../outside.jpg", str(outside), "link.jpg", "https://example.com/a.jpg"]:
        with pytest.raises(ValueError), source.materialize(reference):
            pytest.fail("Escaped media root")


def test_local_media_rejects_directories_empty_and_large_files(tmp_path):
    source = LocalMediaSource(tmp_path, max_bytes=4)
    for filename, content in [("empty", b""), ("large", b"12345")]:
        (tmp_path / filename).write_bytes(content)
        with pytest.raises(ValueError), source.materialize(filename):
            pytest.fail("Invalid media accepted")
    with pytest.raises(ValueError), source.materialize(str(tmp_path)):
        pytest.fail("Directory accepted")
    (tmp_path / "valid").write_bytes(b"1234")
    with source.materialize("valid") as path:
        assert path.read_bytes() == b"1234"
    assert path.exists()  # Local adapter never removes caller-owned media.


def test_image_format_is_validated_from_content(tmp_path):
    path = tmp_path / "fake.jpg"
    Image.new("RGB", (10, 10)).save(path, format="BMP")
    with pytest.raises(ValueError, match="formats"):
        prepare_image(path)
