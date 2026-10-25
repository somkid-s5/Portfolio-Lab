from __future__ import annotations

import os
from functools import lru_cache
from typing import Callable

import pg8000
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import Engine, create_engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create a small reusable pool; local CI may supply DATABASE_URL."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return create_engine(
            database_url,
            pool_size=3,
            max_overflow=0,
            pool_timeout=15,
            pool_pre_ping=True,
        )

    instance = os.environ["INSTANCE_CONNECTION_NAME"]
    database = os.environ.get("DB_NAME", "lab19")
    iam_user = os.environ["DB_IAM_USER"]
    connector = Connector(refresh_strategy="LAZY")

    def connect() -> pg8000.dbapi.Connection:
        return connector.connect(
            instance,
            "pg8000",
            user=iam_user,
            db=database,
            enable_iam_auth=True,
            ip_type=IPTypes.PRIVATE,
        )

    engine = create_engine(
        "postgresql+pg8000://",
        creator=connect,
        pool_size=2,
        max_overflow=0,
        pool_timeout=15,
        pool_recycle=1800,
        pool_pre_ping=True,
    )
    engine._lab19_connector = connector  # Keep the connector alive with the pool.
    return engine


def close_engine(engine: Engine | None = None) -> None:
    target = engine or (get_engine.cache_info().currsize and get_engine())
    if target is None:
        return
    target.dispose()
    connector = getattr(target, "_lab19_connector", None)
    if connector is not None:
        connector.close()
    if engine is None:
        get_engine.cache_clear()
