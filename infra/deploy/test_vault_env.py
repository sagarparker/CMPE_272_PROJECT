import tempfile
import unittest
from pathlib import Path
from unittest import mock

import vault_env

VAULT = "https://kv1.vault.azure.net"


class VaultEnvTests(unittest.TestCase):
    def env_file(self, text):
        path = Path(tempfile.mkdtemp()) / "deploy.env"
        path.write_text(text)
        return path

    def test_file_only_without_vault_name(self):
        path = self.env_file("APP_DOMAIN=x.org\nDATABASE_PASSWORD=local\n")
        with mock.patch.object(vault_env, "_get", side_effect=AssertionError("no network")):
            self.assertEqual(
                vault_env.load(path), {"APP_DOMAIN": "x.org", "DATABASE_PASSWORD": "local"}
            )

    def test_enabled_env_secrets_override_the_file(self):
        path = self.env_file("APP_DOMAIN=x.org\nDATABASE_PASSWORD=old\nKEY_VAULT_NAME=kv1\n")
        pages = {
            f"{VAULT}/secrets?api-version=7.4": {
                "value": [
                    {"id": f"{VAULT}/secrets/db", "contentType": "env:DATABASE_PASSWORD",
                     "attributes": {"enabled": True}},
                    {"id": f"{VAULT}/secrets/off", "contentType": "env:OFF",
                     "attributes": {"enabled": False}},
                    {"id": f"{VAULT}/secrets/note", "contentType": None},
                ],
                "nextLink": None,
            },
            f"{VAULT}/secrets/db?api-version=7.4": {"value": "from-vault"},
        }  # fmt: skip

        def get(url, token=None):
            if url.startswith(vault_env.IMDS):
                self.assertIsNone(token)
                return {"access_token": "managed-identity-token"}
            self.assertEqual(token, "managed-identity-token")
            return pages[url]

        with mock.patch.object(vault_env, "_get", side_effect=get):
            env = vault_env.load(path)
        self.assertEqual(env["DATABASE_PASSWORD"], "from-vault")
        self.assertNotIn("OFF", env)
        self.assertEqual(env["APP_DOMAIN"], "x.org")


if __name__ == "__main__":
    unittest.main()
