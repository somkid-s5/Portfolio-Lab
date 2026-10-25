from __future__ import annotations

import os
from pathlib import Path

import psycopg

SCHEMA = Path(__file__).resolve().parents[1] / "app" / "schema.sql"


def main() -> None:
    conninfo = os.environ.get("PG_DSN")
    if not conninfo:
        raise SystemExit("Set PG_DSN for the disposable test database.")
    statements = [part.strip() for part in SCHEMA.read_text(encoding="utf-8").split(";") if part.strip()]
    with psycopg.connect(conninfo) as conn:
        for statement in statements:
            conn.execute(statement)
    print("schema_ready=true")


if __name__ == "__main__":
    main()
