"""Bounded Cloud SQL IAM-authenticated pool; local mode is for disposable tests only."""
import atexit
import os

from sqlalchemy import create_engine


def create_pool():
    url = os.getenv("DATABASE_URL")
    common = {
        "pool_size": 3,
        "max_overflow": 0,
        "pool_timeout": 4,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "hide_parameters": True,
    }
    if url:
        if os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_JOB"):
            raise ValueError("DATABASE_URL local mode is not allowed on Cloud Run")
        return create_engine(url, connect_args={"timeout": 5}, **common)

    from google.cloud.sql.connector import Connector, IPTypes

    connector = Connector(refresh_strategy="LAZY")
    atexit.register(connector.close)

    def connect():
        return connector.connect(
            os.environ["INSTANCE_CONNECTION_NAME"],
            "pg8000",
            user=os.environ["DB_IAM_USER"],
            db=os.environ["DB_NAME"],
            enable_iam_auth=True,
            ip_type=IPTypes.PRIVATE,
            timeout=5,
        )

    engine = create_engine("postgresql+pg8000://", creator=connect, **common)
    atexit.register(engine.dispose)
    return engine
