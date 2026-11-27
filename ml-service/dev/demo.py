"""Repeatable local queue -> worker -> HTTP search demo. Requires running services."""

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection
from mediamesh_ml.jobs import LocalJobStore, initialize_local_jobs

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--api-url", default="http://ml-api:8000")
parser.add_argument("--retry-demo", action="store_true", help="Needs a writable media mount")
parser.add_argument("--output", type=Path)
args = parser.parse_args()
settings = Settings()
if args.retry_demo and min(settings.job_retry_base_seconds, settings.job_retry_max_seconds) < 1:
    parser.error("Retry demonstration requires a retry delay of at least one second")
if args.retry_demo:
    if settings.job_max_attempts < 2:
        parser.error("Retry demonstration requires at least two attempts")
    if not os.access(settings.media_root, os.W_OK):
        parser.error("Retry demonstration requires the writable tools media mount")
initialize_local_jobs(settings)  # Explicit local-only guard; refuses production asset schema.
store = LocalJobStore(settings)


def register(aid):
    with connection(settings) as conn:
        conn.execute("INSERT INTO assets(id) VALUES (%s) ON CONFLICT DO NOTHING", (aid,))


def wait_for(jid, predicate, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status = store.status(jid)
        if predicate(status):
            return {"jobId": str(jid), **status}
        if status["status"] == "FAILED":
            raise RuntimeError(f"Demo job failed: {status['lastError']}")
        time.sleep(0.25)
    raise RuntimeError("Demo timed out; check ml-worker logs and local queue setup")


with urllib.request.urlopen(args.api_url + "/ready", timeout=10) as response:
    assert response.status == 200

image = UUID("00000000-0000-4000-8000-000000000401")
video = UUID("00000000-0000-4000-8000-000000000501")
for aid in [image, video]:
    register(aid)
jobs = [
    store.enqueue(image, "elephant-02.jpg", "image"),
    store.enqueue(video, "video-bison.mp4", "video"),
]
results = [wait_for(jid, lambda status: status["status"] == "SUCCEEDED") for jid in jobs]

if args.retry_demo:
    retry_asset = uuid4()
    register(retry_asset)
    missing = settings.media_root / f"demo-retry-{retry_asset}.jpg"
    retry_job = store.enqueue(retry_asset, missing.name, "image")
    wait_for(retry_job, lambda status: status["attempts"] >= 1 and status["status"] == "PENDING")
    missing.write_bytes((settings.media_root / "elephant-02.jpg").read_bytes())
    result = wait_for(retry_job, lambda status: status["status"] == "SUCCEEDED")
    if result["attempts"] < 2:
        raise RuntimeError("Expected the initially missing file to require a retry")
    result["mediaReference"] = missing.name
    results.append(result)
    # Retain this small local fixture so the READY asset still has accessible input.

searches = []
for aid, query in [
    (image, "elephants drinking water"),
    (video, "a herd of bison grazing in a green valley"),
]:
    request = urllib.request.Request(
        args.api_url + "/internal/search",
        data=json.dumps({"query": query, "limit": 10}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        matches = json.load(response)["matches"]
    if not any(row["assetId"] == str(aid) for row in matches):
        raise RuntimeError("Expected demo asset was not retrieved")
    searches.append({"query": query, "matches": matches})
report = json.dumps({"jobs": results, "searches": searches}, indent=2) + "\n"
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
print(report)
