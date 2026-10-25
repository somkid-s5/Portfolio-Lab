"""Idempotent SQL migrations and separate least-privilege runtime grants."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from sqlalchemy import text

MIGRATIONS = Path(__file__).with_name("migrations")
_ROLE = re.compile(r"^[a-z][a-z0-9_-]{2,62}$")
_DB_USER = re.compile(r"^[A-Za-z0-9_.@+-]{3,120}$")


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def apply_schema(engine, seed=True, api_role=None, api_user=None, worker_role=None, worker_user=None):
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        version = migration.stem
        with engine.begin() as connection:
            done = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE version=:version"),
                {"version": version},
            ).first()
            if done:
                continue
            for statement in (part.strip() for part in migration.read_text(encoding="utf-8").split(";")):
                if statement and not statement.startswith("--"):
                    connection.exec_driver_sql(statement)
            connection.execute(
                text("INSERT INTO schema_migrations(version) VALUES (:version)"),
                {"version": version},
            )

    if seed:
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            current = connection.execute(text("SELECT COUNT(*) FROM slots")).scalar_one()
            if current == 0:
                slots = [
                    ("consult-morning", "Cloud design consultation · morning", now + timedelta(days=7), 2),
                    ("consult-afternoon", "Cloud design consultation · afternoon", now + timedelta(days=7, hours=4), 2),
                    ("handover-workshop", "Platform handover workshop", now + timedelta(days=8, hours=1), 3),
                ]
                for slot_id, label, start, capacity in slots:
                    connection.execute(
                        text(
                            "INSERT INTO slots(slot_id, label, starts_at, capacity, booked) "
                            "VALUES (:id, :label, :starts, :capacity, 0) "
                            "ON CONFLICT(slot_id) DO NOTHING"
                        ),
                        {"id": slot_id, "label": label, "starts": start.isoformat(timespec="minutes"),
                         "capacity": capacity},
                    )

    if engine.dialect.name == "postgresql" and api_role and worker_role:
        grant_runtime_access(engine, api_role, api_user, worker_role, worker_user)


def grant_runtime_access(engine, api_role, api_user, worker_role, worker_user):
    for role in (api_role, worker_role):
        if not _ROLE.fullmatch(role):
            raise ValueError("Database roles must be lowercase PostgreSQL role names")
    for user in (api_user, worker_user):
        if not user or not _DB_USER.fullmatch(user):
            raise ValueError("IAM database usernames must be supplied and valid")

    with engine.begin() as connection:
        database = quote_identifier(connection.execute(text("SELECT current_database()")).scalar_one())
        owner = quote_identifier(connection.execute(text("SELECT current_user")).scalar_one())
        for role_name in (api_role, worker_role):
            exists = connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname=:name"), {"name": role_name}
            ).first()
            if not exists:
                connection.exec_driver_sql(f"CREATE ROLE {quote_identifier(role_name)} NOLOGIN")
            role = quote_identifier(role_name)
            connection.exec_driver_sql(f"GRANT CONNECT ON DATABASE {database} TO {role}")
            connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")

        api = quote_identifier(api_role)
        worker = quote_identifier(worker_role)
        connection.exec_driver_sql(f"GRANT SELECT, UPDATE ON slots TO {api}")
        connection.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE ON bookings TO {api}")
        connection.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE ON report_jobs TO {api}")
        connection.exec_driver_sql(f"GRANT SELECT ON bookings TO {worker}")
        connection.exec_driver_sql(f"GRANT SELECT, UPDATE ON report_jobs TO {worker}")
        connection.exec_driver_sql(f"GRANT {api} TO {quote_identifier(api_user)}")
        connection.exec_driver_sql(f"GRANT {worker} TO {quote_identifier(worker_user)}")
