"""Run on the deployment VM to add the account-creation client to an existing realm.

Fresh deployments get this client from prepare.py. The client's service account
holds only realm-management/manage-users. Its secret is appended to the private
deploy.env as KEYCLOAK_PROVISIONER_SECRET; rebuild the backend afterwards.
"""

import argparse
import json
import secrets
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = "mediamesh-provisioner"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-domain", required=True)
    args = parser.parse_args()
    env_file = ROOT / "infra/deploy/runtime/deploy.env"
    env = dict(x.split("=", 1) for x in env_file.read_text().splitlines() if "=" in x)
    if args.expect_domain != env["APP_DOMAIN"]:
        raise SystemExit("Deployment domain does not match explicit target")
    if env.get("KEYCLOAK_PROVISIONER_SECRET"):
        raise SystemExit("KEYCLOAK_PROVISIONER_SECRET already exists; nothing changed")

    # compose.sh cannot interpolate compose.deploy.yaml until the secret exists, so use labels.
    container = subprocess.check_output(["sudo", "docker", "ps", "-q",
        "--filter", "label=com.docker.compose.project=mediamesh-deploy",
        "--filter", "label=com.docker.compose.service=keycloak"], text=True).strip()
    if not container or "\n" in container:
        raise SystemExit("Expected exactly one running Keycloak container")
    networks = json.loads(subprocess.check_output(["sudo", "docker", "inspect", container], text=True))[0]["NetworkSettings"]["Networks"]
    base = "http://" + next(iter(networks.values()))["IPAddress"] + ":8080/auth"
    headers = {"Host": env["APP_DOMAIN"], "X-Forwarded-Proto": "https", "X-Forwarded-Host": env["APP_DOMAIN"]}

    def call(method, path, body=None, form=None):
        data = urllib.parse.urlencode(form).encode() if form else json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(base + path, data=data, method=method, headers=dict(headers))
        if body is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read()
            return json.loads(text) if text else None

    token = call("POST", "/realms/master/protocol/openid-connect/token", form={
        "client_id": "admin-cli", "grant_type": "password",
        "username": "deployment-admin", "password": env["KEYCLOAK_ADMIN_PASSWORD"]})["access_token"]
    headers["Authorization"] = "Bearer " + token
    realm = "/admin/realms/mediamesh"
    if call("GET", f"{realm}/clients?clientId={CLIENT}"):
        raise SystemExit(f"{CLIENT} already exists but deploy.env has no secret; fix manually")

    secret = secrets.token_hex(32)
    call("POST", f"{realm}/clients", {
        "clientId": CLIENT, "publicClient": False, "secret": secret, "serviceAccountsEnabled": True,
        "standardFlowEnabled": False, "implicitFlowEnabled": False, "directAccessGrantsEnabled": False,
        "fullScopeAllowed": False})
    client = call("GET", f"{realm}/clients?clientId={CLIENT}")[0]["id"]
    management = call("GET", f"{realm}/clients?clientId=realm-management")[0]["id"]
    role = call("GET", f"{realm}/clients/{management}/roles/manage-users")
    scope = next(s for s in call("GET", f"{realm}/client-scopes") if s["name"] == "kc-admin-api")
    call("PUT", f"{realm}/clients/{client}/default-client-scopes/{scope['id']}", {})
    call("POST", f"{realm}/clients/{client}/scope-mappings/clients/{management}", [role])
    account = call("GET", f"{realm}/clients/{client}/service-account-user")["id"]
    call("POST", f"{realm}/users/{account}/role-mappings/clients/{management}", [role])

    with env_file.open("a") as handle:
        handle.write(f"KEYCLOAK_PROVISIONER_SECRET={secret}\n")
    print(f"Added {CLIENT} with manage-users only. Rebuild: sudo ./infra/deploy/compose.sh up -d --build backend frontend")


if __name__ == "__main__":
    main()
