"""Local-only Azurite bootstrap using Microsoft's public, non-secret fixture."""

from urllib.parse import urlparse

ACCOUNT = "devstoreaccount1"
KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="


def emulator_client(endpoint):
    from azure.storage.blob import BlobServiceClient

    uri = urlparse(endpoint)
    if (
        uri.scheme != "http"
        or uri.hostname not in {"azurite", "localhost", "127.0.0.1"}
        or uri.path != "/devstoreaccount1"
        or not uri.port
        or uri.username
        or uri.password
        or uri.query
        or uri.fragment
    ):
        raise ValueError("Azurite requires a local HTTP endpoint for devstoreaccount1")
    return BlobServiceClient(
        endpoint,
        credential={"account_name": ACCOUNT, "account_key": KEY},
        api_version="2023-11-03",
        connection_timeout=3,
        read_timeout=30,
        retry_total=2,
        max_single_get_size=1024 * 1024,
        max_chunk_get_size=1024 * 1024,
    )


if __name__ == "__main__":
    from azure.core.exceptions import ResourceExistsError

    from mediamesh_ml.config import Settings

    settings = Settings()
    with emulator_client(settings.azure_emulator_endpoint) as client:
        try:
            client.create_container(settings.azure_storage_container)
        except ResourceExistsError:
            pass
        # Local browser PUTs need the same CORS contract as cloud Blob Storage.
        from azure.storage.blob import CorsRule

        client.set_service_properties(
            cors=[
                CorsRule(
                    allowed_origins=["http://localhost:8080"],
                    allowed_methods=["GET", "HEAD", "PUT", "OPTIONS"],
                    allowed_headers=[
                        "content-type",
                        "if-none-match",
                        "x-ms-blob-type",
                        "x-ms-version",
                        "range",
                    ],
                    exposed_headers=["ETag"],
                    max_age_in_seconds=300,
                )
            ]
        )
    print("Local private Blob container and browser CORS are ready.")
