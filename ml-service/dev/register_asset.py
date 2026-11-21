"""Register a UUID in the minimal standalone local asset fixture only."""

import argparse
from uuid import UUID

from mediamesh_ml.config import Settings
from mediamesh_ml.database import connection

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("asset_id", type=UUID)
args = parser.parse_args()
with connection(Settings()) as conn:
    if conn.info.dbname != "mediamesh" or conn.info.host != "postgres":
        raise ValueError("Fixture registration requires the standalone Compose database")
    columns = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='assets' ORDER BY ordinal_position"
    ).fetchall()
    if columns != [("id",)]:
        raise ValueError("Refusing to register against a production asset schema")
    conn.execute("INSERT INTO assets(id) VALUES (%s) ON CONFLICT DO NOTHING", (args.asset_id,))
print(args.asset_id)
