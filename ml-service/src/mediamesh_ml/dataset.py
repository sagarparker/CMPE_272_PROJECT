"""Checksum-verified download of the curated evaluation manifest."""

import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

USER_AGENT = "MediaMesh/0.1 (CMPE272 educational local retrieval evaluation)"


def read_manifest(path: Path) -> list[dict]:
    items = json.loads(path.read_text())["items"]
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("Duplicate sample IDs")
    for item in items:
        if Path(item["filename"]).name != item["filename"]:
            raise ValueError("Sample filenames must be basenames")
        url = urlparse(item["download_url"])
        wikimedia = url.hostname in {"upload.wikimedia.org", "thumb.wikimedia.org"}
        nps = url.hostname == "www.nps.gov" and url.path.startswith("/nps-audiovideo/")
        if url.scheme != "https" or not (wikimedia or nps):
            raise ValueError("Expected an approved Wikimedia or NPS HTTPS media URL")
    return items


def download(item: dict, directory: Path) -> Path:
    expected = item["sha256"]
    if not expected or len(expected) != 64:
        raise ValueError("Manifest must contain a pinned SHA-256")
    path = directory / item["filename"]
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
        return path
    request = urllib.request.Request(item["download_url"], headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                content = response.read(20_000_001)
            if len(content) > 20_000_000:
                raise ValueError("Sample exceeds 20 MB download bound")
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError(f"Checksum mismatch for {item['id']}; do not silently refresh")
            temporary = path.with_suffix(".part")
            temporary.write_bytes(content)
            temporary.replace(path)
            return path
        except OSError:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("Unreachable")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("evaluation/manifest.json"))
    parser.add_argument("--directory", type=Path, default=Path("/data/media"))
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    for item in read_manifest(args.manifest):
        print(download(item, args.directory), flush=True)


if __name__ == "__main__":
    main()
