"""Add demo-manifest photos/videos to the Azure catalog that are not there yet.

Runs inside the deployed ml-worker container, which already has the VM managed
identity for Blob Storage and the catalog database:

    sudo ./infra/deploy/seed-azure.sh

For each manifest item missing from the catalog it downloads the pinned file,
verifies its SHA-256, writes it create-only to Blob Storage, records the asset under
the domain's demo uploader (same title, metadata and credit format as
frontend/scripts/seed-demo.mjs) and queues an indexing job, exactly as the upload
API's complete step does. The normal ml-worker then embeds and captions it.

Downloads are checked against the manifest SHA-256. Wikimedia's regional caches can
serve a different rendering of a thumbnail; place verified copies in
``/tmp/demo-cache/<filename>`` inside the container (see seed-azure.sh) and they are
used instead of downloading.

Nothing is overwritten. Items already imported (listed in demo-upload-state.json or
found by owner + title + source page) are skipped, and a changed checksum for an
already-imported item stops the run.
"""

import hashlib
import json
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import ContentSettings

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection
from mediamesh_ml.media import AzureBlobMediaSource

USER_AGENT = "MediaMesh-CMPE272-course-demo/1.0 (educational; contact via repository)"
MAX_BYTES = 100_000_000
TYPES = {"image": ("image/jpeg", (b"\xff\xd8\xff",)), "video": ("video/mp4", (b"ftyp",))}


def credit(item):
    return (
        f"{item['license']}. Credit: {item['creator']}. Source: {item['source_page']}. "
        f"License: {item.get('license_url') or item['source_page']}. "
        "Curated for the MediaMesh educational demo; verify rights before publication."
    )


def media_type(item):
    return "video" if item["filename"].lower().endswith(".mp4") else "image"


def safe_filename(name):
    name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)
    return name or "media"


CACHE = Path("/tmp/demo-cache")


def download(item):
    cached = CACHE / Path(item["filename"]).name
    if cached.is_file():
        return verify(item, cached.read_bytes())
    request = urllib.request.Request(item["download_url"], headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read(MAX_BYTES + 1)
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    return verify(item, data)


def verify(item, data):
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("empty or over the 100 MB upload limit")
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("SHA-256 does not match the manifest")
    content_type, magic = TYPES[media_type(item)]
    head = data[:12]
    if not any(head.startswith(m) or m in head for m in magic):
        raise ValueError(f"file is not {content_type}")
    return data, content_type


def main():
    payload = json.load(sys.stdin)
    manifest, state = payload["manifest"]["items"], payload["state"]
    settings = Settings()
    container = AzureBlobMediaSource(settings).client.get_container_client(
        settings.azure_storage_container
    )
    with connection(settings) as conn:
        owners = dict(
            conn.execute(
                "SELECT email, id FROM users WHERE email LIKE 'demo.%%@mediamesh.local' "
                "AND deleted_at IS NULL"
            ).fetchall()
        )
    added = skipped = 0
    for item in manifest:
        known = state["assets"].get(item["id"])
        if known:
            if known["sha256"] != item["sha256"]:
                raise SystemExit(f"Seed source changed for {item['id']}; review before replacing")
            skipped += 1
            continue
        owner = owners.get(f"demo.{item['domain']}@mediamesh.local")
        if owner is None:
            raise SystemExit(f"No demo uploader for domain {item['domain']}")
        title = f"{item['domain'][0].upper()}{item['domain'][1:]} | {item['title']}"[:255]
        with connection(settings) as conn:
            existing = conn.execute(
                "SELECT id FROM assets WHERE owner_id=%s AND title=%s AND usage_note LIKE %s",
                (owner, title, f"%{item['source_page']}%"),
            ).fetchone()
        if existing:
            state["assets"][item["id"]] = {
                "assetId": str(existing[0]), "ownerId": str(owner), "sha256": item["sha256"],
            }  # fmt: skip
            print(json.dumps({"event": "found", "id": item["id"], **state["assets"][item["id"]]}))
            skipped += 1
            continue
        try:
            data, content_type = download(item)
        except Exception as error:
            print(json.dumps({"event": "error", "id": item["id"], "error": str(error)[:200]}))
            continue
        asset_id = uuid.uuid4()
        kind = media_type(item)
        key = f"assets/{owner}/{asset_id}/source/{safe_filename(item['filename'])}"
        try:
            container.upload_blob(
                key, data, overwrite=False, timeout=120,
                content_settings=ContentSettings(content_type=content_type),
            )  # fmt: skip
        except ResourceExistsError:
            print(json.dumps({"event": "error", "id": item["id"], "error": "blob key exists"}))
            continue
        with connection(settings) as conn:
            conn.execute(
                "INSERT INTO assets(id, owner_id, s3_key, media_type, title, description, species, "
                "location, captured_at, contributor, usage_note, processing_status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PROCESSING')",
                (
                    asset_id, owner, key, kind, title,
                    (item.get("description") or item["title"])[:4000],
                    item.get("species") or None, item.get("location") or None,
                    item.get("capturedAt") or None, item["creator"][:255], credit(item)[:4000],
                ),
            )  # fmt: skip
            conn.execute(
                "INSERT INTO index_jobs(id, asset_id, media_reference, media_type) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (uuid.uuid4(), asset_id, key, kind),
            )
        state["assets"][item["id"]] = {
            "assetId": str(asset_id), "ownerId": str(owner), "sha256": item["sha256"],
        }  # fmt: skip
        print(json.dumps({"event": "added", "id": item["id"], **state["assets"][item["id"]]}))
        added += 1
        time.sleep(0.3)  # Be polite to Wikimedia.
    print(json.dumps({"event": "done", "added": added, "skipped": skipped}))


if __name__ == "__main__":
    main()
