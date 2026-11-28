"""Load deployment settings: non-secret values from deploy.env, secrets from Azure Key Vault.

When deploy.env sets KEY_VAULT_NAME, every enabled vault secret whose content type is
``env:NAME`` is exported as NAME. The VM's managed identity reads the vault through the
instance metadata service, so no credential is stored on disk. Vault values override
deploy.env. Without KEY_VAULT_NAME the file is used on its own (fresh/local setups).

``python3 vault_env.py exec CMD...`` runs CMD with the merged environment; nothing is
written to disk.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "infra/deploy/runtime/deploy.env"
IMDS = "http://169.254.169.254/metadata/identity/oauth2/token"


def read_file(path=ENV_FILE):
    return dict(x.split("=", 1) for x in path.read_text().splitlines() if "=" in x)


def _get(url, token=None):
    headers = {"Metadata": "true"} if token is None else {"Authorization": "Bearer " + token}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
        return json.load(r)


def vault_secrets(vault):
    query = urllib.parse.urlencode({"api-version": "2018-02-01", "resource": "https://vault.azure.net"})
    token = _get(f"{IMDS}?{query}")["access_token"]
    base = f"https://{vault}.vault.azure.net"
    secrets, url = {}, f"{base}/secrets?api-version=7.4"
    while url:
        page = _get(url, token)
        for item in page.get("value", []):
            kind = item.get("contentType") or ""
            if kind.startswith("env:") and item.get("attributes", {}).get("enabled", True):
                secrets[kind[4:]] = _get(item["id"] + "?api-version=7.4", token)["value"]
        url = page.get("nextLink")
    return secrets


def load(path=ENV_FILE):
    values = read_file(path)
    vault = values.get("KEY_VAULT_NAME", "").strip()
    if vault:
        values.update(vault_secrets(vault))
    return values


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "exec":
        raise SystemExit("usage: vault_env.py exec COMMAND [ARGS...]")
    env = dict(os.environ)
    env.update(load())
    os.execvpe(sys.argv[2], sys.argv[2:], env)


if __name__ == "__main__":
    main()
