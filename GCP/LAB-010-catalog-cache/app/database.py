import os

from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine, text

POOL_SIZE = 3


def create_database_engine():
    database_url = os.getenv("DATABASE_URL")
    common = {
        "pool_size": POOL_SIZE,
        "max_overflow": 0,
        "pool_timeout": 2,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
    if database_url:
        return create_engine(database_url, **common)

    instance = os.environ["INSTANCE_CONNECTION_NAME"]
    database = os.environ.get("DB_NAME", "catalog")
    user = os.environ["DB_IAM_USER"]
    connector = Connector(refresh_strategy="LAZY")

    def connect():
        return connector.connect(
            instance,
            "pg8000",
            user=user,
            db=database,
            enable_iam_auth=True,
            ip_type=IPTypes.PRIVATE,
            timeout=10,
        )

    engine = create_engine("postgresql+pg8000://", creator=connect, **common)
    engine._lab_connector = connector
    return engine


def close_database_engine(engine):
    connector = getattr(engine, "_lab_connector", None)
    engine.dispose()
    if connector is not None:
        connector.close()


def check_database(engine):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
