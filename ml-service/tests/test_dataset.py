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
