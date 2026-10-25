from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.database import get_engine

ROLE_NAMES = ("lab19_api_role", "lab19_worker_role")
MIGRATION = Path(__file__).with_name("migration.sql")


def migrate(engine=None) -> None:
    target = engine or get_engine()
    with target.begin() as connection:
        for role_name in ROLE_NAMES:
            exists = connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :name"),
                {"name": role_name},
            ).first()
            if not exists:
                connection.exec_driver_sql(f'CREATE ROLE "{role_name}" NOLOGIN')
        statements = MIGRATION.read_text(encoding="utf-8").split("-- migrate:split")
        for statement in statements:
            statement = statement.strip()
            if statement:
                connection.exec_driver_sql(statement)
        verified = connection.execute(
            text(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema = 'lab19' AND table_name = 'tasks'
                """
            )
        ).first()
        if not verified:
            raise RuntimeError("Migration verification failed: lab19.tasks is absent")


def main() -> None:
    migrate()
    print("migration_status=applied schema=lab19 table=tasks api_role=lab19_api_role worker_role=lab19_worker_role")


if __name__ == "__main__":
    main()
