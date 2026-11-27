"""Explicit, bounded database connections; no schema changes at API startup."""

from contextlib import contextmanager

import psycopg

from mediamesh_ml.config import Settings


@contextmanager
def connection(settings: Settings):
    with psycopg.connect(
        settings.database_url.get_secret_value(),
        connect_timeout=settings.db_connect_timeout_seconds,
        tcp_user_timeout=15000,
        options=(f"-c statement_timeout={settings.db_statement_timeout_ms} -c lock_timeout=5000"),
    ) as conn:
        yield conn


def database_status(settings: Settings) -> dict[str, bool]:
    with connection(settings) as conn:
        row = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector'), "
            "to_regclass('public.asset_vectors') IS NOT NULL"
        ).fetchone()
    return {"vector_extension": row[0], "vector_table": row[1]}


if __name__ == "__main__":
    import json

    print(json.dumps(database_status(Settings())))
