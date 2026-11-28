"""Run on the deployment VM to provision only the seven curated demo identities.

Credentials stay in private runtime files. Application roles are bootstrapped by
the SSH operator; no application ADMIN role or localhost password is imported.
"""

import argparse
import json
import os
import secrets
import subprocess
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-domain", required=True)
    args = parser.parse_args()
    private = ROOT / "infra/deploy/runtime"
    from vault_env import load

    env = load(private / "deploy.env")  # includes Key Vault secrets when configured
    if args.expect_domain != env["APP_DOMAIN"]:
        raise ValueError("Deployment domain does not match explicit target")
    os.umask(0o077)
    fixture = json.loads((ROOT / "infra/demo/accounts.json").read_text())
    expected = {"demo." + x for x in ("wildlife", "plants", "oceans", "marine", "birds", "landscapes", "researcher")}
    if {a["username"] for a in fixture["accounts"]} != expected:
        raise ValueError("Only the seven known demo accounts may be provisioned")
    path = private / "demo-accounts.json"
    if not path.exists():
        accounts = []
        for account in fixture["accounts"]:
            account = dict(account)
            account.update(subject=str(uuid.uuid4()), appId=str(uuid.uuid4()), password=secrets.token_hex(24))
            accounts.append(account)
        path.write_text(json.dumps({"origin": "https://" + env["APP_DOMAIN"], "accounts": accounts}, indent=2) + "\n")
    state = json.loads(path.read_text())
    if state["origin"] != "https://" + env["APP_DOMAIN"] or {a["username"] for a in state["accounts"]} != expected:
        raise ValueError("Saved demo identities do not match this deployment")

    compose = ["sudo", str(ROOT / "infra/deploy/compose.sh")]
    container = run(compose + ["ps", "-q", "keycloak"])
    network = json.loads(run(["sudo", "docker", "inspect", container]))[0]["NetworkSettings"]["Networks"]
    base = "http://" + next(iter(network.values()))["IPAddress"] + ":8080/auth"
    headers = {"Host": env["APP_DOMAIN"], "X-Forwarded-Proto": "https", "X-Forwarded-Host": env["APP_DOMAIN"]}
    data = urllib.parse.urlencode({"client_id": "admin-cli", "grant_type": "password", "username": "deployment-admin", "password": env["KEYCLOAK_ADMIN_PASSWORD"]}).encode()
    with urllib.request.urlopen(urllib.request.Request(base + "/realms/master/protocol/openid-connect/token", data=data, headers=headers), timeout=15) as response:
        token = json.load(response)["access_token"]
    headers.update(Authorization="Bearer " + token, **{"Content-Type": "application/json"})
    sql = ["BEGIN;"]
    issuer = state["origin"] + "/auth/realms/mediamesh"
    for account in state["accounts"]:
        expected_roles = ["UPLOADER"] if account["domain"] else ["RESEARCHER"]
        if account["roles"] != expected_roles:
            raise ValueError("Unexpected demo role; ADMIN is never granted")
        route = base + "/admin/realms/mediamesh/users?exact=true&username=" + urllib.parse.quote(account["username"])
        with urllib.request.urlopen(urllib.request.Request(route, headers=headers), timeout=15) as response:
            found = json.load(response)
        if found:
            if len(found) != 1 or found[0]["id"] != account["subject"] or found[0].get("email") != account["email"]:
                raise ValueError("Existing identity collision; no credentials overwritten")
        else:
            body = {"id": account["subject"], "username": account["username"], "firstName": account["firstName"], "lastName": account["lastName"], "email": account["email"], "emailVerified": True, "enabled": True, "attributes": {"mediamesh_demo_import": ["nature-v1"]}, "credentials": [{"type": "password", "value": account["password"], "temporary": False}]}
            with urllib.request.urlopen(urllib.request.Request(base + "/admin/realms/mediamesh/users", data=json.dumps(body).encode(), headers=headers), timeout=15) as response:
                if response.status != 201:
                    raise RuntimeError("Identity was not created")
                account["subject"] = response.headers["Location"].rsplit("/", 1)[1]
            path.write_text(json.dumps(state, indent=2) + "\n")
        app_id, subject = account["appId"], account["subject"]
        uuid.UUID(app_id)
        uuid.UUID(subject)
        values = [app_id, issuer, subject, account["email"], account["firstName"] + " " + account["lastName"]]
        sql.append("INSERT INTO users(id,issuer,subject,email,display_name) VALUES(" + ",".join(map(literal, values)) + ") ON CONFLICT(issuer,subject) DO NOTHING;")
        sql.append("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM users WHERE id=" + literal(app_id) + " AND issuer=" + literal(issuer) + " AND subject=" + literal(subject) + ") OR EXISTS(SELECT 1 FROM user_roles WHERE user_id=" + literal(app_id) + " AND role<>" + literal(expected_roles[0]) + ") THEN RAISE EXCEPTION 'Demo identity or role collision'; END IF; END $$;")
        sql.append("INSERT INTO user_roles(user_id,role) VALUES(" + literal(app_id) + "," + literal(expected_roles[0]) + ") ON CONFLICT DO NOTHING;")
        sql.append("INSERT INTO audit_events(actor_id,action,target,detail) SELECT " + literal(app_id) + ",'DEPLOYMENT_DEMO_PROVISION'," + literal(app_id) + ",'SSH operator provisioned nature-v1 demo account; no ADMIN grant' WHERE NOT EXISTS(SELECT 1 FROM audit_events WHERE actor_id=" + literal(app_id) + " AND action='DEPLOYMENT_DEMO_PROVISION');")
    sql.append("COMMIT;")
    run(compose + ["exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "mediamesh", "-d", "mediamesh"], input="\n".join(sql))
    print("Seven demo identities and least-privilege application roles provisioned. Passwords remain in runtime/demo-accounts.json.")


if __name__ == "__main__":
    main()
