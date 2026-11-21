"""Standalone local job adapter. Production job integration remains a backend handoff."""

import argparse
import json
from pathlib import Path
from uuid import UUID, uuid4

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection


def initialize_local_jobs(settings: Settings):
    with connection(settings) as conn:
        if conn.info.dbname not in {"mediamesh", "mediamesh_test"} or conn.info.host not in {
            "postgres",
            "postgres-test",
        }:
            raise ValueError("Local jobs require a standalone Compose database")
        columns = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='assets' ORDER BY ordinal_position"
        ).fetchall()
        if columns != [("id",)]:
            raise ValueError("Refusing local fixtures against a production asset schema")
        conn.execute(Path("dev/bootstrap_jobs.sql").read_text(), prepare=False)


class LocalJobStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    def enqueue(self, asset_id: UUID, reference: str, media_type: str) -> UUID:
        if not reference.strip() or media_type not in {"image", "video"}:
            raise ValueError("Expected a media reference and image/video type")
        with connection(self.settings) as conn:
            if not conn.execute(
                "SELECT id FROM public.assets WHERE id=%s FOR UPDATE", (asset_id,)
            ).fetchone():
                raise ValueError("Register the local asset before enqueueing")
            active = conn.execute(
                "SELECT id, media_reference, media_type FROM ml_dev.index_jobs "
                "WHERE asset_id=%s AND status IN ('PENDING','PROCESSING')",
                (asset_id,),
            ).fetchone()
            if active:
                if active[1:] != (reference, media_type):
                    raise ValueError("Asset already has a different active job")
                return active[0]
            job_id = uuid4()
            conn.execute(
                "INSERT INTO ml_dev.index_jobs(id, asset_id, media_reference, media_type, "
                "max_attempts) VALUES (%s,%s,%s,%s,%s)",
                (job_id, asset_id, reference, media_type, self.settings.job_max_attempts),
            )
            conn.execute(
                "INSERT INTO ml_dev.asset_states VALUES (%s,'PROCESSING') "
                "ON CONFLICT (asset_id) DO UPDATE SET processing_status='PROCESSING'",
                (asset_id,),
            )
        return job_id

    def status(self, job_id: UUID) -> dict:
        with connection(self.settings) as conn:
            row = conn.execute(
                "SELECT status, attempts, max_attempts, last_error FROM ml_dev.index_jobs WHERE id=%s",
                (job_id,),
            ).fetchone()
        if not row:
            raise ValueError("Job does not exist")
        return dict(zip(["status", "attempts", "maxAttempts", "lastError"], row, strict=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("--asset-id", type=UUID, required=True)
    enqueue.add_argument("--reference", required=True)
    enqueue.add_argument("--media-type", choices=["image", "video"], required=True)
    status = sub.add_parser("status")
    status.add_argument("job_id", type=UUID)
    args = parser.parse_args()
    settings = Settings()
    store = LocalJobStore(settings)
    if args.command == "init":
        initialize_local_jobs(settings)
        print("Local job fixtures initialized")
    elif args.command == "enqueue":
        print(
            json.dumps(
                {"jobId": str(store.enqueue(args.asset_id, args.reference, args.media_type))}
            )
        )
    else:
        print(json.dumps(store.status(args.job_id)))


if __name__ == "__main__":
    main()
