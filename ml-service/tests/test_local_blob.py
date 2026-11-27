import pytest

from mediamesh_ml.local_blob import emulator_client


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://account.blob.core.windows.net/devstoreaccount1",
        "http://untrusted.example:10000/devstoreaccount1",
        "http://localhost:10000/realaccount",
        "http://user:password@localhost:10000/devstoreaccount1",
    ],
)
def test_emulator_credential_cannot_be_sent_to_a_cloud_or_untrusted_endpoint(endpoint):
    with pytest.raises(ValueError, match="local HTTP endpoint"):
        emulator_client(endpoint)


def test_emulator_accepts_only_its_public_test_account():
    with emulator_client("http://localhost:10000/devstoreaccount1") as client:
        assert client.account_name == "devstoreaccount1"
