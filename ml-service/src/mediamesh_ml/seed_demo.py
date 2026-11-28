"""Seed selected images into the local integrated catalog owned by its Google admin."""

import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection
from mediamesh_ml.dataset import IMAGE_COUNTS, download, read_manifest, select_images
from mediamesh_ml.local_blob import emulator_client

ISSUER = "http://localhost:8080/auth/realms/mediamesh"
# Must match IdentityService.PENDING_ADMIN_SUBJECT; the backend claims this row on
# the administrator's first verified Google sign-in.
PENDING_ADMIN_SUBJECT = "pending-google-admin:"


def local_admin(settings, email):
    if settings.azure_emulator_endpoint != "http://azurite:10000/devstoreaccount1":
        raise ValueError("Demo seeding requires the local Azurite emulator")
    if not settings.production_mode:
        raise ValueError("Demo seeding requires the integrated catalog")
    with connection(settings) as conn:
        if conn.info.host != "postgres" or conn.info.dbname != "mediamesh":
            raise ValueError("Demo seeding requires the local Compose database")
        # Same lock as the backend's administrator bootstrap.
        conn.execute("SELECT pg_advisory_xact_lock(27201)")
        rows = conn.execute(
            "SELECT id FROM users WHERE lower(email)=lower(%s) AND issuer=%s "
            "AND primary_admin AND deleted_at IS NULL "
            "AND EXISTS (SELECT 1 FROM user_roles WHERE user_id=users.id AND role='ADMIN')",
            (email, ISSUER),
        ).fetchall()
        if len(rows) == 1:
            return rows[0][0]
        return pending_admin(conn, email)


def pending_admin(conn, email):
    """Reserve the administrator account before its first Google sign-in."""
    known = conn.execute(
        "SELECT 1 FROM users WHERE lower(email)=lower(%s) AND issuer=%s", (email, ISSUER),
    ).fetchone()
    other = conn.execute(
        "SELECT email FROM users WHERE primary_admin AND lower(email)<>lower(%s)", (email,),
    ).fetchone()
    if known or other:
        # An existing account or a previous administrator needs the backend's own handover.
        raise ValueError("Sign in with Google as ADMIN_EMAIL at http://localhost:8080 first")
    owner = uuid4()
    conn.execute(
        "INSERT INTO users(id,issuer,subject,email,display_name,primary_admin) "
        "VALUES (%s,%s,%s,%s,%s,true)",
        (owner, ISSUER, PENDING_ADMIN_SUBJECT + email.lower(), email, email),
    )
    conn.execute("INSERT INTO user_roles VALUES (%s,'ADMIN')", (owner,))
    conn.execute(
        "INSERT INTO audit_events(actor_id,action,target,detail) "
        "VALUES (%s,'BOOTSTRAP_ADMIN',%s,'Reserved by local demo seed before Google sign-in')",
        (owner, str(owner)),
    )
    print(f"Reserved {email} as administrator; sign in with Google later to claim it",
          flush=True)
    return owner


def provider(route, token=None, data=None, method=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(
        "http://keycloak:8080/auth" + route, data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read()
        return json.loads(body) if body else None


def remove_legacy_users(settings, owner, fixture):
    """Remove only known local password fixtures; preserve their uploads and audit rows."""
    accounts = fixture["accounts"] + [
        {"username": name, "email": f"{name}@mediamesh.local"}
        for name in ("admin", "uploader", "researcher", "employee")
    ]
    token = provider("/realms/master/protocol/openid-connect/token", data={
        "client_id": "admin-cli", "grant_type": "password",
        "username": "local-admin", "password": "local-development-only",
    })["access_token"]
    for account in accounts:
        found = provider("/admin/realms/mediamesh/users?exact=true&username="
                         + urllib.parse.quote(account["username"]), token)
        for user in found:
            # Never remove a Google-linked account, even if a username was reused.
            linked = provider(f"/admin/realms/mediamesh/users/{user['id']}/federated-identity",
                              token)
            if user.get("email") != account["email"] or linked:
                raise ValueError(f"Legacy identity no longer matches: {account['username']}")
            with connection(settings) as conn:
                rows = conn.execute(
                    "SELECT id FROM users WHERE issuer=%s AND subject=%s AND id<>%s "
                    "AND NOT primary_admin FOR UPDATE", (ISSUER, user["id"], owner),
                ).fetchall()
                for (uid,) in rows:
                    conn.execute("UPDATE assets SET owner_id=%s WHERE owner_id=%s", (owner, uid))
                    conn.execute("DELETE FROM user_roles WHERE user_id=%s", (uid,))
                    conn.execute("UPDATE api_sessions SET revoked=true WHERE user_id=%s", (uid,))
                    conn.execute(
                        "UPDATE access_requests SET status='REJECTED',reviewed_by=%s,"
                        "reviewed_at=clock_timestamp() WHERE user_id=%s AND status='PENDING'",
                        (owner, uid),
                    )
                    conn.execute(
                        "UPDATE users SET deleted_at=clock_timestamp() WHERE id=%s", (uid,)
                    )
            provider(f"/admin/realms/mediamesh/users/{user['id']}", token, method="DELETE")
            print(f"Removed legacy dummy login: {account['username']}", flush=True)


def seed_image(settings, client, owner, item, directory):
    # Stable IDs let retries recover even when the host-side report is lost.
    aid = uuid5(NAMESPACE_URL, f"mediamesh:demo:{item['id']}:{item['sha256']}")
    title = f"{item['domain'].capitalize()} | {item['title']}"[:255]
    credit = (f"{item['license']}. Credit: {item['creator']}. Source: {item['source_page']}. "
              f"License: {item.get('license_url') or item['source_page']}.")
    with connection(settings) as conn:
        # Recover old browser-seeded images after transferring dummy users' uploads.
        existing = conn.execute(
            "SELECT id,s3_key,processing_status FROM assets WHERE id=%s OR "
            "(owner_id=%s AND title=%s AND position(%s in usage_note)>0) "
            "ORDER BY created_at LIMIT 1 FOR UPDATE",
            (aid, owner, title, item["source_page"]),
        ).fetchone()
        key = f"assets/{owner}/{aid}/source/{item['filename']}"
        if existing:
            aid, key, status = existing
            if status == "FAILED":
                raise ValueError(f"Indexing failed for {item['id']}; inspect worker logs")
            if status != "UPLOADING":
                return aid
        else:
            conn.execute(
                "INSERT INTO assets(id,owner_id,s3_key,media_type,title,description,species,"
                "location,captured_at,contributor,usage_note,processing_status) "
                "VALUES (%s,%s,%s,'image',%s,%s,%s,%s,%s,%s,%s,'UPLOADING')",
                (aid, owner, key, title, item.get("description") or item["title"],
                 item.get("species"), item.get("location"), item.get("capturedAt"),
                 item["creator"], credit),
            )
    from azure.storage.blob import ContentSettings

    # Replacing this script's UPLOADING object is safe after an interrupted PUT.
    with (directory / item["filename"]).open("rb") as media:
        client.get_blob_client(settings.azure_storage_container, key).upload_blob(
            media, overwrite=True, content_settings=ContentSettings(content_type="image/jpeg")
        )
    with connection(settings) as conn:
        changed = conn.execute(
            "UPDATE assets SET processing_status='PROCESSING',updated_at=clock_timestamp() "
            "WHERE id=%s AND processing_status='UPLOADING' RETURNING id", (aid,),
        ).fetchone()
        if changed:
            conn.execute(
                "INSERT INTO index_jobs(id,asset_id,media_reference,media_type) "
                "VALUES (%s,%s,%s,'image')", (uuid4(), aid, key),
            )
    return aid


def wait_ready(settings, ids, timeout=7200):
    deadline = time.monotonic() + timeout
    while True:
        with connection(settings) as conn:
            rows = conn.execute(
                "SELECT processing_status,count(*) FROM assets WHERE id=ANY(%s::uuid[]) "
                "GROUP BY processing_status", (ids,),
            ).fetchall()
        counts = dict(rows)
        if counts.get("FAILED"):
            raise RuntimeError("Seed image indexing failed; inspect worker logs")
        ready = counts.get("READY", 0)
        print(f"READY {ready}/{len(ids)}", flush=True)
        if ready == len(ids):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Indexing did not finish; rerun to resume")
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=int, choices=IMAGE_COUNTS, default=20)
    args = parser.parse_args()
    settings = Settings()
    email = os.environ.get("ADMIN_EMAIL", "").strip()
    if not email:
        parser.error("Set ADMIN_EMAIL in the root .env file")
    owner = local_admin(settings, email)
    # Serialize operators so concurrent runs cannot overwrite a blob being indexed.
    with connection(settings) as lock:
        if not lock.execute("SELECT pg_try_advisory_lock(27202)").fetchone()[0]:
            raise RuntimeError("Another local seed run is active")
        lock.commit()
        run_seed(settings, email, owner, args.images)


def run_seed(settings, email, owner, count):
    items = select_images(read_manifest(Path("/evaluation/demo-manifest.json")), count)
    directory = Path("/data/demo")
    directory.mkdir(parents=True, exist_ok=True)
    # Validate/download only the chosen subset, before changing catalog data.
    for item in items:
        if not all(item.get(field) for field in ("creator", "license", "source_page")):
            raise ValueError(f"Missing credits: {item['id']}")
        media = download(item, directory)
        if hashlib.sha256(media.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Checksum mismatch: {item['id']}")
    fixture = json.loads(Path("/demo-config/accounts.json").read_text())
    remove_legacy_users(settings, owner, fixture)
    with emulator_client(settings.azure_emulator_endpoint) as client:
        ids = []
        for item in items:
            ids.append(seed_image(settings, client, owner, item, directory))
            print(f"Seeded {len(ids)}/{len(items)}: {item['id']}", flush=True)
    wait_ready(settings, ids)
    from mediamesh_ml.seed_enrich import enrich

    enrich(settings, ids)
    report = {"images": len(ids), "ownerId": str(owner), "assetIds": [str(aid) for aid in ids]}
    temporary = directory / "seed-report.json.tmp"
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(directory / "seed-report.json")
    print(f"Verified {len(ids)} images for {email}", flush=True)


if __name__ == "__main__":
    main()
