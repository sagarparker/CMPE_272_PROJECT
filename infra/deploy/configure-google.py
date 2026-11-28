"""Configure Google brokering on an existing Keycloak realm without reimporting users.

Credentials are read from the environment, never command-line arguments. This
changes only the Google provider and the web client's identity-provider mapper.
"""

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path


def configure(base, realm, username, password, client_id, client_secret, public_host=None):
    headers = ({"Host": public_host, "X-Forwarded-Host": public_host, "X-Forwarded-Proto": "https"}
               if public_host else {})

    def call(method, path, body=None, form=None):
        data = (urllib.parse.urlencode(form).encode() if form else
                json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers=headers)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if form:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request, timeout=15) as response:
            result = response.read()
            return json.loads(result) if result else None

    token = call("POST", "/realms/master/protocol/openid-connect/token", form={
        "grant_type": "password", "client_id": "admin-cli", "username": username, "password": password})
    headers["Authorization"] = "Bearer " + token["access_token"]
    root = "/admin/realms/" + urllib.parse.quote(realm, safe="")
    template = json.loads((Path(__file__).resolve().parents[1] / "keycloak/mediamesh-realm.json").read_text())
    provider = template["identityProviders"][0]
    provider["config"].update(clientId=client_id, clientSecret=client_secret)
    existing = call("GET", root + "/identity-provider/instances")
    match = next((p for p in existing if p["alias"] == "google"), None)
    if match:
        provider["internalId"] = match["internalId"]
    call("PUT" if match else "POST", root + "/identity-provider/instances" + ("/google" if match else ""), provider)
    [client] = call("GET", root + "/clients?clientId=mediamesh-web")
    mapper_root = root + "/clients/" + client["id"] + "/protocol-mappers/models"
    mapper = next(m for m in template["clients"][0]["protocolMappers"] if m["name"] == "identity-provider")
    match = next((m for m in call("GET", mapper_root) if m["name"] == mapper["name"]), None)
    if match:
        mapper["id"] = match["id"]
    call("PUT" if match else "POST", mapper_root + ("/" + match["id"] if match else ""), mapper)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Keycloak base URL, including /auth")
    parser.add_argument("--realm", default="mediamesh")
    parser.add_argument("--username", default="deployment-admin", help="Keycloak master-realm operator")
    parser.add_argument("--public-host", help="Hosted domain when calling Keycloak over its private network")
    args = parser.parse_args()
    names = ("KEYCLOAK_ADMIN_PASSWORD", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    if any(not os.environ.get(name) for name in names):
        parser.error("Set " + ", ".join(names) + " in the environment")
    configure(args.url, args.realm, args.username, *(os.environ[name] for name in names), public_host=args.public_host)
    print("Configured Google sign-in and identity-provider token mapper. Existing users were preserved.")


if __name__ == "__main__":
    main()
