from __future__ import annotations

import os
from pathlib import Path

import psycopg

SCHEMA = Path(__file__).resolve().parents[1] / "app" / "schema.sql"


def main() -> None:
    conninfo = os.environ.get("PG_DSN")
    app_password = os.environ.get("CI_APP_DB_PASSWORD")
    if not conninfo or not app_password:
        raise SystemExit("Set PG_DSN and CI_APP_DB_PASSWORD for the disposable CI database.")
    statements = [part.strip() for part in SCHEMA.read_text(encoding="utf-8").split(";") if part.strip()]
    with psycopg.connect(conninfo) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'records_app'").fetchone()
        if exists:
            conn.execute("ALTER ROLE records_app WITH LOGIN PASSWORD %s", (app_password,))
        else:
            conn.execute("CREATE ROLE records_app WITH LOGIN PASSWORD %s", (app_password,))
        for statement in statements:
            conn.execute(statement)
        conn.execute("GRANT CONNECT ON DATABASE lab017_ci TO records_app")
    print("schema_ready=true runtime_role=records_app delete_privilege=false")


if __name__ == "__main__":
    main()
