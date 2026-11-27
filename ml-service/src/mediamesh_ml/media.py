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


class AzureBlobMediaSource:
    """Materialize a private catalog blob using the VM managed identity."""

    def __init__(self, settings, *, client=None):
        self.max_bytes = settings.media_max_bytes
        self.container = settings.azure_storage_container
        if client is None:
            from azure.identity import ManagedIdentityCredential
            from azure.storage.blob import BlobServiceClient

            if settings.azure_emulator_endpoint:
                from mediamesh_ml.local_blob import emulator_client

                self.client = emulator_client(settings.azure_emulator_endpoint)
                return
            if not settings.azure_storage_account:
                raise ValueError("ML_AZURE_STORAGE_ACCOUNT is required")
            client = BlobServiceClient(
                account_url=f"https://{settings.azure_storage_account}.blob.core.windows.net",
                credential=ManagedIdentityCredential(connection_timeout=3, read_timeout=5),
                connection_timeout=5,
                read_timeout=30,
                retry_total=2,
                max_single_get_size=1024 * 1024,
                max_chunk_get_size=1024 * 1024,
            )
        self.client = client

    @contextmanager
    def materialize(self, reference: str):
        import tempfile

        from azure.core import MatchConditions

        if not reference.startswith("assets/") or "://" in reference or "\x00" in reference:
            raise ValueError("Expected a catalog blob key")
        blob = self.client.get_blob_client(container=self.container, blob=reference)
        properties = blob.get_blob_properties(timeout=30)
        if not 0 < properties.size <= self.max_bytes:
            raise ValueError("Media is empty or exceeds size limit")
        with tempfile.TemporaryDirectory(prefix="mediamesh-") as directory:
            path = Path(directory) / ("source" + Path(reference).suffix)
            downloaded = blob.download_blob(
                timeout=30,
                max_concurrency=1,
                etag=properties.etag,
                match_condition=MatchConditions.IfNotModified,
            )
            total = 0
            with path.open("wb") as output:
                for chunk in downloaded.chunks():
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise ValueError("Media exceeds size limit")
                    output.write(chunk)
            if total != properties.size:
                raise OSError("Incomplete blob download")
            yield path

    def upload(self, key: str, path: Path, content_type: str) -> None:
        """Write a derived catalog object (for example a playback copy)."""
        from azure.storage.blob import ContentSettings

        if not key.startswith("assets/") or "/source/" in key:
            raise ValueError("Derived objects must not overwrite catalog sources")
        with path.open("rb") as data:
            self.client.get_blob_client(container=self.container, blob=key).upload_blob(
                data,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
                timeout=120,
                max_concurrency=1,
            )
