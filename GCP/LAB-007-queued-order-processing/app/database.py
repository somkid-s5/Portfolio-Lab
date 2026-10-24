"""Role-bound Cloud SQL private connector and a bounded SQLAlchemy DB-API pool."""
from dataclasses import dataclass
import os
from pathlib import Path
import re

from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine
from order_domain import read_json

USERS = {"portal":"order_api","worker":"order_worker","dispatcher":"outbox_dispatcher"}
POOL_SIZES = {"portal":2,"worker":2,"dispatcher":1}
FORBIDDEN_ENV = (
    "GOOGLE_APPLICATION_CREDENTIALS","PUBSUB_EMULATOR_HOST","FIRESTORE_EMULATOR_HOST",
    "STORAGE_EMULATOR_HOST","PGHOST","PGPORT","PGDATABASE","PGUSER","PGPASSWORD",
    "DATABASE_URL","DB_HOST",
)


def read_credentials(path, role):
    if role not in USERS:
        raise ValueError("invalid_database_role")
    with Path(path).open("rb") as handle:
        value = read_json(handle.read(4097))
    if (set(value) != {"user","password","database"} or
            value["user"] != USERS[role] or value["database"] != "order_queue" or
            not isinstance(value["password"],str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{32,128}",value["password"])):
        raise ValueError("invalid_database_bundle")
    return value


def make_pool(creator, size):
    if type(size) is not int or size not in (1,2):
        raise ValueError("invalid_pool_size")
    return create_engine(
        "postgresql+pg8000://", creator=creator,
        pool_size=size,max_overflow=0,pool_timeout=2,
        pool_pre_ping=True,pool_recycle=1800,pool_use_lifo=True,
        pool_reset_on_return="rollback",hide_parameters=True,echo=False)


@dataclass(repr=False)
class Database:
    engine: object
    connector: object

    def connect(self):
        return self.engine.raw_connection()

    def close(self):
        try:
            self.engine.dispose()
        finally:
            self.connector.close()


def build_database(role, *, environ=None):
    env = os.environ if environ is None else environ
    if role not in USERS:
        raise ValueError("invalid_database_role")
    if (env.get("K_SERVICE") != "lab007-"+role or env.get("SERVICE_ROLE") != role or
            any(env.get(key) for key in FORBIDDEN_ENV)):
        raise ValueError("attached_cloud_service_identity_required")
    project = env.get("GOOGLE_CLOUD_PROJECT")
    if not isinstance(project,str) or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]",project):
        raise ValueError("invalid_project")
    instance = env.get("SQL_INSTANCE_CONNECTION_NAME")
    if instance != f"{project}:asia-southeast1:lab007-orders":
        raise ValueError("invalid_instance_binding")
    version = env.get("DB_SECRET_VERSION")
    if not isinstance(version,str) or not re.fullmatch(r"[1-9][0-9]{0,9}",version):
        raise ValueError("numeric_secret_version_required")
    path = env.get("DB_SECRET_FILE")
    if path != "/secrets/db/db.json":
        raise ValueError("fixed_secret_mount_required")
    credentials = read_credentials(path,role)
    connector = Connector(ip_type=IPTypes.PRIVATE,refresh_strategy="LAZY",
                          timeout=5,enable_iam_auth=False)
    def creator():
        return connector.connect(
            instance,"pg8000",user=credentials["user"],password=credentials["password"],
            db="order_queue",ip_type=IPTypes.PRIVATE,enable_iam_auth=False,timeout=5)
    try:
        engine = make_pool(creator,POOL_SIZES[role])
    except BaseException:
        connector.close()
        raise
    return Database(engine,connector)
