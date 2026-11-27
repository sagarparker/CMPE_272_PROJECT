"""Leased PostgreSQL job store for production catalogs and isolated local fixtures."""

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import ClaimedJob, VectorRecord
from mediamesh_ml.database import connection
from mediamesh_ml.vectors import replace_in_transaction


class StaleClaim(RuntimeError):
    """A recovered/reassigned job cannot be completed by its former owner."""


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


class PostgresJobStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jobs_table = "public.index_jobs" if settings.production_mode else "ml_dev.index_jobs"
        self.states_table = "public.assets" if settings.production_mode else "ml_dev.asset_states"
        self.state_key = "id" if settings.production_mode else "asset_id"

    def enqueue(self, asset_id: UUID, reference: str, media_type: str) -> UUID:
        if self.settings.production_mode:
            raise ValueError("Production jobs must be created through the backend upload API")
        if not reference.strip() or media_type not in {"image", "video"}:
            raise ValueError("Expected a media reference and image/video type")
        with connection(self.settings) as conn:
            if not conn.execute(
                "SELECT id FROM public.assets WHERE id=%s FOR UPDATE", (asset_id,)
            ).fetchone():
                raise ValueError("Register the local asset before enqueueing")
            active = conn.execute(
                f"SELECT id, media_reference, media_type FROM {self.jobs_table} "
                "WHERE asset_id=%s AND status IN ('PENDING','PROCESSING')",
                (asset_id,),
            ).fetchone()
            if active:
                if active[1:] != (reference, media_type):
                    raise ValueError("Asset already has a different active job")
                return active[0]
            job_id = uuid4()
            conn.execute(
                f"INSERT INTO {self.jobs_table}(id, asset_id, media_reference, media_type, "
                "max_attempts) VALUES (%s,%s,%s,%s,%s)",
                (job_id, asset_id, reference, media_type, self.settings.job_max_attempts),
            )
            conn.execute(
                f"INSERT INTO {self.states_table} VALUES (%s,'PROCESSING') "
                "ON CONFLICT (asset_id) DO UPDATE SET processing_status='PROCESSING'",
                (asset_id,),
            )
        return job_id

    def _recover(self, conn):
        expired = conn.execute(
            f"SELECT id, asset_id, attempts, max_attempts FROM {self.jobs_table} "
            "WHERE status='PROCESSING' AND lease_expires_at<=clock_timestamp() "
            "ORDER BY lease_expires_at LIMIT 100 FOR UPDATE SKIP LOCKED"
        ).fetchall()
        for jid, aid, attempts, maximum in expired:
            terminal = attempts >= maximum
            conn.execute(
                f"UPDATE {self.jobs_table} SET status=%s, claim_token=NULL, lease_expires_at=NULL, "
                "available_at=clock_timestamp()+(%s * interval '1 second'), "
                "last_error='LeaseExpired' WHERE id=%s",
                ("FAILED" if terminal else "PENDING", self._delay(attempts), jid),
            )
            conn.execute(
                f"UPDATE {self.states_table} SET processing_status=%s WHERE {self.state_key}=%s",
                ("FAILED" if terminal else "PROCESSING", aid),
            )

    def _delay(self, attempt):
        return min(
            self.settings.job_retry_base_seconds * 2 ** (attempt - 1),
            self.settings.job_retry_max_seconds,
        )

    def claim(self) -> ClaimedJob | None:
        with connection(self.settings) as conn:
            self._recover(conn)
            row = conn.execute(
                "SELECT id, asset_id, media_reference, media_type, attempts "
                f"FROM {self.jobs_table} WHERE status='PENDING' AND attempts<max_attempts "
                "AND available_at<=clock_timestamp() ORDER BY available_at, created_at, id "
                "LIMIT 1 FOR UPDATE SKIP LOCKED"
            ).fetchone()
            if not row:
                return None
            token = uuid4()
            conn.execute(
                f"UPDATE {self.jobs_table} SET status='PROCESSING', attempts=attempts+1, "
                "claim_token=%s, lease_expires_at=clock_timestamp()+(%s * interval '1 second') "
                "WHERE id=%s",
                (token, self.settings.job_lease_seconds, row[0]),
            )
            return ClaimedJob(row[0], row[1], row[2], row[3], str(token), row[4] + 1)

    def renew(self, job: ClaimedJob) -> bool:
        with connection(self.settings) as conn:
            return bool(
                conn.execute(
                    f"UPDATE {self.jobs_table} SET lease_expires_at=clock_timestamp()+"
                    "(%s * interval '1 second') WHERE id=%s AND claim_token=%s "
                    "AND status='PROCESSING' AND lease_expires_at>clock_timestamp() RETURNING id",
                    (self.settings.job_lease_seconds, job.job_id, UUID(job.claim_token)),
                ).fetchone()
            )

    def _require_claim(self, conn, job):
        row = conn.execute(
            f"SELECT asset_id, media_type, attempts FROM {self.jobs_table} WHERE id=%s "
            "AND claim_token=%s AND status='PROCESSING' "
            "AND lease_expires_at>clock_timestamp() FOR UPDATE",
            (job.job_id, UUID(job.claim_token)),
        ).fetchone()
        if not row or row != (job.asset_id, job.media_type, job.attempt):
            raise StaleClaim("Job lease is expired or no longer owned")

    def complete(
        self, job: ClaimedJob, records: Sequence[VectorRecord], *, playback_key: str | None = None
    ) -> None:
        if not records:
            raise ValueError("Cannot mark an empty index READY")
        if job.media_type == "image" and (
            len(records) != 1 or records[0].frame_timestamp_seconds is not None
        ):
            raise ValueError("Image jobs require one image vector")
        if job.media_type == "video" and any(r.frame_timestamp_seconds is None for r in records):
            raise ValueError("Video jobs require timestamped vectors")
        with connection(self.settings) as conn:
            self._require_claim(conn, job)
            replace_in_transaction(conn, job.asset_id, records[0].model_version, records)
            conn.execute(
                f"UPDATE {self.jobs_table} SET status='SUCCEEDED', claim_token=NULL, "
                "lease_expires_at=NULL, last_error=NULL WHERE id=%s",
                (job.job_id,),
            )
            conn.execute(
                f"UPDATE {self.states_table} SET processing_status='READY' "
                f"WHERE {self.state_key}=%s",
                (job.asset_id,),
            )
            if playback_key is not None and self.settings.production_mode:
                conn.execute(
                    "UPDATE public.assets SET playback_key=%s WHERE id=%s",
                    (playback_key, job.asset_id),
                )

    def fail(self, job: ClaimedJob, error: str, *, retryable: bool) -> None:
        # Persist error codes, never arbitrary media URLs, paths, or exception messages.
        code = error if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", error) else "ProcessingError"
        with connection(self.settings) as conn:
            self._require_claim(conn, job)
            maximum = conn.execute(
                f"SELECT max_attempts FROM {self.jobs_table} WHERE id=%s", (job.job_id,)
            ).fetchone()[0]
            terminal = not retryable or job.attempt >= maximum
            conn.execute(
                f"UPDATE {self.jobs_table} SET status=%s, last_error=%s, claim_token=NULL, "
                "lease_expires_at=NULL, available_at=clock_timestamp()+(%s * interval '1 second') "
                "WHERE id=%s",
                ("FAILED" if terminal else "PENDING", code, self._delay(job.attempt), job.job_id),
            )
            conn.execute(
                f"UPDATE {self.states_table} SET processing_status=%s WHERE {self.state_key}=%s",
                ("FAILED" if terminal else "PROCESSING", job.asset_id),
            )

    def status(self, job_id: UUID) -> dict:
        with connection(self.settings) as conn:
            row = conn.execute(
                f"SELECT status, attempts, max_attempts, last_error FROM {self.jobs_table} "
                "WHERE id=%s",
                (job_id,),
            ).fetchone()
        if not row:
            raise ValueError("Job does not exist")
        return dict(zip(["status", "attempts", "maxAttempts", "lastError"], row, strict=True))


# Preserve the standalone development import used by existing demos/tests.
class LocalJobStore(PostgresJobStore):
    def __init__(self, settings: Settings):
        super().__init__(settings.model_copy(update={"production_mode": False}))


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
