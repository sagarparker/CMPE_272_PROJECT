from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.media import AzureBlobMediaSource


def source(chunks, size=5):
    client = Mock()
    blob = client.get_blob_client.return_value
    blob.get_blob_properties.return_value = SimpleNamespace(size=size, etag='"version"')
    blob.download_blob.return_value.chunks.return_value = iter(chunks)
    return AzureBlobMediaSource(Settings(media_max_bytes=5), client=client), client, blob


def test_blob_is_scoped_version_checked_and_temporary():
    media, client, blob = source([b"im", b"age"])
    with media.materialize("assets/owner/photo.jpg") as path:
        assert path.read_bytes() == b"image"
        temporary = Path(path)
    assert not temporary.exists()
    client.get_blob_client.assert_called_once_with(
        container="mediamesh", blob="assets/owner/photo.jpg"
    )
    assert blob.download_blob.call_args.kwargs["etag"] == '"version"'
    with pytest.raises(ValueError):
        with media.materialize("https://untrusted.example/photo"):
            pass


@pytest.mark.parametrize(
    "chunks,size,error",
    [
        ([b"image!"], 6, ValueError),
        ([b"image!"], 5, ValueError),
        ([b"im"], 5, OSError),
        ([], 0, ValueError),
    ],
)
def test_blob_rejects_oversize_empty_and_partial_downloads(chunks, size, error):
    media, _, _ = source(chunks, size)
    with pytest.raises(error):
        with media.materialize("assets/owner/photo.jpg"):
            pass


def test_decoder_failure_removes_blob_temp_file():
    media, _, _ = source([b"image"])
    with pytest.raises(RuntimeError):
        with media.materialize("assets/owner/photo.jpg") as path:
            temporary = path
            raise RuntimeError("Decoder failed")
    assert not temporary.exists()
