"""Explicit standalone local migrations; production V3xx files belong to backend Flyway."""

import argparse
import hashlib
from pathlib import Path

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection


def apply_migrations(settings: Settings, directory: Path, *, fixture: Path | None = None):
    files = sorted(directory.glob("V3[0-9][0-9]__*.sql"))
    if not files:
        raise ValueError("No V3xx migration files found")
    with connection(settings) as conn:
        # Serialize migration runners; the whole batch commits or rolls back together.
        conn.execute("SELECT pg_advisory_xact_lock(300272)")
        if fixture:
            if conn.info.dbname not in {"mediamesh", "mediamesh_test"} or conn.info.host not in {
                "postgres",
                "postgres-test",
            }:
                raise ValueError("Local fixture requires the Compose development/test database")
            conn.execute(fixture.read_text(), prepare=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ml_schema_migrations (
                filename TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        for path in files:
            content = path.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            applied = conn.execute(
                "SELECT sha256 FROM ml_schema_migrations WHERE filename=%s", (path.name,)
            ).fetchone()
            if applied:
                if applied[0] != checksum:
                    raise ValueError(f"Applied migration changed: {path.name}")
                continue
            conn.execute(content.decode(), prepare=False)
            conn.execute(
                "INSERT INTO ml_schema_migrations(filename, sha256) VALUES (%s, %s)",
                (path.name, checksum),
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("/app/migrations"))
    parser.add_argument("--local-fixture", action="store_true")
    args = parser.parse_args()
    apply_migrations(
        Settings(),
        args.directory,
        fixture=Path("dev/bootstrap_assets.sql") if args.local_fixture else None,
    )
    print("Vector migrations are current")


if __name__ == "__main__":
    main()
