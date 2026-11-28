"""Opt-in isolated release identity/database smoke test; creates and removes its own Docker volumes."""

import json
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare import ROOT, prepare


def run(args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


with tempfile.TemporaryDirectory(prefix="mediamesh-release-") as directory:
    tmp = Path(directory)
    private = tmp / "runtime"
    prepare(
        "archive.mediamesh-demo.org",
        "ops@mediamesh-demo.org",
        "mediameshsmoketest",
        "owner@mediamesh-demo.org",
        "mediamesh",
        private,
    )
    config = json.loads(
        run(
            [
                "docker",
                "compose",
                "--env-file",
                str(private / "deploy.env"),
                "-f",
                str(ROOT / "compose.deploy.yaml"),
                "config",
                "--format",
                "json",
            ]
        )
    )
    config["name"] = "mediamesh-release-check-" + uuid.uuid4().hex[:8]
    config["services"] = {
        key: value
        for key, value in config["services"].items()
        if key in {"postgres", "keycloak"}
    }
    config["services"]["keycloak"]["ports"] = [
        {"target": 8080, "host_ip": "127.0.0.1", "protocol": "tcp"}
    ]
    for mount in config["services"]["keycloak"]["volumes"]:
        if mount["target"] == "/opt/keycloak/data/import":
            mount["source"] = str(private / "realm")
    config["volumes"] = {"postgres-data": {}}
    path = tmp / "compose.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    compose = ["docker", "compose", "-f", str(path)]
    try:
        run(compose + ["up", "-d"])
        address = run(compose + ["port", "keycloak", "8080"]).strip()
        url = "http://" + address + "/auth"
        headers = {
            "Host": "archive.mediamesh-demo.org",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "archive.mediamesh-demo.org",
        }
        for attempt in range(50):
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(
                        url + "/realms/mediamesh/.well-known/openid-configuration",
                        headers=headers,
                    ),
                    timeout=3,
                ) as response:
                    discovery = json.load(response)
                break
            except OSError:
                time.sleep(2)
        else:
            raise RuntimeError("Release Keycloak did not become ready")
        assert (
            discovery["issuer"]
            == "https://archive.mediamesh-demo.org/auth/realms/mediamesh"
        )
        env = dict(
            line.split("=", 1)
            for line in (private / "deploy.env").read_text().splitlines()
        )
        body = urllib.parse.urlencode(
            {
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": "deployment-admin",
                "password": env["KEYCLOAK_ADMIN_PASSWORD"],
            }
        ).encode()
        with urllib.request.urlopen(
            urllib.request.Request(
                url + "/realms/master/protocol/openid-connect/token",
                data=body,
                headers=headers,
            ),
            timeout=5,
        ) as response:
            token = json.load(response)["access_token"]
        with urllib.request.urlopen(
            urllib.request.Request(
                url + "/admin/realms/mediamesh/users",
                headers={**headers, "Authorization": "Bearer " + token},
            ),
            timeout=5,
        ) as response:
            users = json.load(response)
        assert all(user.get("serviceAccountClientId") for user in users)
        run(compose + ["stop", "keycloak"])
        for database in ["mediamesh", "keycloak"]:
            backup = tmp / (database + ".dump")
            with backup.open("wb") as file:
                subprocess.run(
                    compose
                    + [
                        "exec",
                        "-T",
                        "postgres",
                        "pg_dump",
                        "-U",
                        "mediamesh",
                        "-Fc",
                        database,
                    ],
                    stdout=file,
                    stderr=subprocess.PIPE,
                    check=True,
                )
            with backup.open("rb") as file:
                subprocess.run(
                    compose
                    + [
                        "exec",
                        "-T",
                        "postgres",
                        "pg_restore",
                        "-U",
                        "mediamesh",
                        "-d",
                        database,
                        "--clean",
                        "--if-exists",
                        "--exit-on-error",
                    ],
                    stdin=file,
                    capture_output=True,
                    check=True,
                )
        restored = run(
            compose
            + [
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "mediamesh",
                "-d",
                "keycloak",
                "-Atc",
                "SELECT count(*) FROM user_entity WHERE username='service-account-mediamesh-provisioner'",
            ]
        ).strip()
        assert restored == "1"
        print(
            "PASS: both database dumps restore successfully and preserve the provisioner service account"
        )
        print(
            "PASS: production-mode Keycloak + PostgreSQL startup, HTTPS issuer, Google-ready realm; no local application users"
        )
    finally:
        run(compose + ["down", "-v"])
