"""Cloud Run Job entry point for tracked migrations and environment-scoped grants."""
import os

from sqlalchemy import text

from app.database import create_pool
from app.database_schema import apply_schema


def migrate(engine=None):
    target = engine or create_pool()
    apply_schema(
        target,
        seed=True,
        api_role=os.getenv("DB_API_ROLE"),
        api_user=os.getenv("DB_API_USER"),
        worker_role=os.getenv("DB_WORKER_ROLE"),
        worker_user=os.getenv("DB_WORKER_USER"),
    )
    with target.connect() as connection:
        versions = connection.execute(
            text("SELECT version FROM schema_migrations ORDER BY version")
        ).scalars().all()
    print(
        "migration_status=applied database="
        + os.getenv("DB_NAME", "local")
        + " versions="
        + ",".join(versions)
    )


if __name__ == "__main__":
    migrate()
