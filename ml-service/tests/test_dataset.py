import hashlib
import json

import pytest

from mediamesh_ml.dataset import download, read_manifest


def test_cached_download_needs_matching_checksum(tmp_path):
    path = tmp_path / "test.jpg"
    path.write_bytes(b"cached image")
    item = {"filename": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert download(item, tmp_path) == path
    item["sha256"] = None
    with pytest.raises(ValueError, match="pinned"):
        download(item, tmp_path)


def test_manifest_rejects_path_escape(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"items": [{"id": "x", "filename": "../outside"}]}))
    with pytest.raises(ValueError, match="basenames"):
        read_manifest(path)


def test_pinned_regional_variant_is_accepted_from_cache_and_download(tmp_path, monkeypatch):
    from io import BytesIO

    canonical = hashlib.sha256(b"canonical").hexdigest()
    variant = b"regional variant"
    item = {"id": "test", "filename": "test.jpg", "sha256": canonical,
            "sha256_alternates": [hashlib.sha256(variant).hexdigest()],
            "download_url": "https://thumb.wikimedia.org/test.jpg"}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: BytesIO(variant))
    assert download(item, tmp_path).read_bytes() == variant
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: pytest.fail("valid cache should be reused"))
    assert download(item, tmp_path).read_bytes() == variant


def test_unknown_variant_is_rejected_without_writing_file(tmp_path, monkeypatch):
    from io import BytesIO

    item = {"id": "test", "filename": "test.jpg", "sha256": "a" * 64,
            "sha256_alternates": ["b" * 64], "download_url": "https://thumb.wikimedia.org/test.jpg"}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: BytesIO(b"unapproved bytes"))
    with pytest.raises(ValueError, match="Checksum mismatch"):
        download(item, tmp_path)
    assert not (tmp_path / "test.jpg").exists()


@pytest.mark.parametrize("alternates", ["a" * 64, ["bad"], [None]])
def test_invalid_alternate_pins_are_rejected(tmp_path, alternates):
    with pytest.raises(ValueError, match="SHA-256"):
        download({"filename": "test.jpg", "sha256": "a" * 64,
                  "sha256_alternates": alternates}, tmp_path)
