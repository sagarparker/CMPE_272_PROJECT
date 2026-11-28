"""Generate private, fresh-deployment configuration; never modify a running realm."""

import argparse
import copy
import json
import os
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def prepare(domain, email, account, admin_email, container, output):
    if not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain
    ):
        raise ValueError("Use a DNS hostname, without a scheme, port or path")
    if domain in {"example.com", "localhost"} or domain.endswith(
        (".example.com", ".local", ".invalid")
    ):
        raise ValueError("Use your real public hostname")
    for value in (email, admin_email):
        if not re.fullmatch(r"[a-zA-Z0-9._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", value):
            raise ValueError("Supply a valid email address")
    if not re.fullmatch(r"[a-z0-9]{3,24}", account):
        raise ValueError("Azure storage account needs 3–24 lowercase letters/digits")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9]|-(?!-)){1,61}[a-z0-9]", container):
        raise ValueError(
            "Azure container needs 3–63 lowercase letters/digits/hyphens without consecutive hyphens"
        )
    if output.exists():
        raise ValueError(
            "Configuration already exists; back it up and edit deliberately rather than regenerating identities"
        )
    realm = copy.deepcopy(
        json.loads((ROOT / "infra/keycloak/mediamesh-realm.json").read_text())
    )
    origin = f"https://{domain}"
    realm.update(
        sslRequired="external",
        bruteForceProtected=True,
        passwordPolicy="length(14) and notUsername(undefined)",
    )
    client = realm["clients"][0]
    client.update(redirectUris=[origin + "/*"], webOrigins=[origin])
    client["attributes"]["post.logout.redirect.uris"] = origin + "/*"
    provisioner_secret = secrets.token_hex(32)
    provisioner = next(c for c in realm["clients"] if c["clientId"] == "mediamesh-provisioner")
    provisioner["secret"] = provisioner_secret
    service_account = next(u for u in realm["users"] if u.get("serviceAccountClientId"))
    # Google creates sign-in identities on first login; no local application administrator.
    realm["users"] = [service_account]
    values = {
        "APP_DOMAIN": domain,
        "ACME_EMAIL": email,
        "AZURE_STORAGE_ACCOUNT": account,
        "AZURE_STORAGE_CONTAINER": container,
        "DATABASE_PASSWORD": secrets.token_hex(32),
        "KEYCLOAK_DB_PASSWORD": secrets.token_hex(32),
        "KEYCLOAK_ADMIN_PASSWORD": secrets.token_hex(32),
        "KEYCLOAK_PROVISIONER_SECRET": provisioner_secret,
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
    }
    os.umask(0o077)
    output.mkdir(parents=True, mode=0o700)
    (output / "realm").mkdir(mode=0o755)
    (output / "realm").chmod(0o755)
    realm_file = output / "realm/mediamesh-realm.json"
    realm_file.write_text(json.dumps(realm, indent=2) + "\n")
    # Keycloak's non-root container needs read access; the parent stays private.
    realm_file.chmod(0o644)
    (output / "deploy.env").write_text(
        "".join(f"{key}={value}\n" for key, value in values.items())
    )
    (output / "first-login.txt").write_text(
        f"URL: {origin}\nSign in with Google as sagar.parker@sjsu.edu.\n"
        "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in deploy.env before starting Keycloak.\n"
    )
    (output / "azure-cors.json").write_text(
        json.dumps(
            {
                "allowedOrigins": [origin],
                "allowedMethods": ["GET", "HEAD", "PUT", "OPTIONS"],
                "allowedHeaders": [
                    "content-type",
                    "if-none-match",
                    "x-ms-blob-type",
                    "x-ms-version",
                    "range",
                ],
                "exposedHeaders": ["ETag"],
                "maxAgeInSeconds": 300,
            },
            indent=2,
        )
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--email", required=True, help="Certificate renewal contact")
    parser.add_argument("--account", required=True)
    parser.add_argument("--admin-email", default="sagar.parker@sjsu.edu", help="Legacy argument; application admin is fixed to sagar.parker@sjsu.edu")
    parser.add_argument("--container", default="mediamesh")
    args = parser.parse_args()
    try:
        prepare(
            args.domain,
            args.email,
            args.account,
            args.admin_email,
            args.container,
            ROOT / "infra/deploy/runtime",
        )
    except ValueError as error:
        parser.error(str(error))
    print(
        "Prepared private files in infra/deploy/runtime/. No cloud resources created."
    )
    print("Keep deploy.env, realm/ and first-login.txt private; back them up securely.")


if __name__ == "__main__":
    main()
