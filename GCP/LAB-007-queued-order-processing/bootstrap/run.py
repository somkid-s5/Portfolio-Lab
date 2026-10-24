"""One-off Cloud Run Job. No public endpoint, role adoption, migration or reset."""
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from google.cloud.sql.connector import Connector,IPTypes
from order_domain import read_json
from installer import install,validate_bundles

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN=("K_SERVICE","GOOGLE_APPLICATION_CREDENTIALS","PGHOST","PGPORT","PGDATABASE","PGUSER",
           "PGPASSWORD","DATABASE_URL","DB_HOST","PUBSUB_EMULATOR_HOST","FIRESTORE_EMULATOR_HOST")
VERSIONS=("BOOTSTRAP_SECRET_VERSION","PORTAL_DB_SECRET_VERSION",
          "WORKER_DB_SECRET_VERSION","DISPATCHER_DB_SECRET_VERSION")


def configuration(env):
    if (env.get("CLOUD_RUN_JOB")!="lab007-bootstrap" or env.get("SERVICE_ROLE")!="bootstrap"
            or any(env.get(key) for key in FORBIDDEN)):
        raise ValueError("one_off_attached_job_required")
    project=env.get("GOOGLE_CLOUD_PROJECT")
    if not isinstance(project,str) or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]",project):
        raise ValueError("invalid_project")
    instance=env.get("SQL_INSTANCE_CONNECTION_NAME")
    if instance!=f"{project}:asia-southeast1:lab007-orders":
        raise ValueError("invalid_instance_binding")
    if any(not isinstance(env.get(key),str) or not re.fullmatch(r"[1-9][0-9]{0,9}",env[key])
           for key in VERSIONS):
        raise ValueError("numeric_secret_versions_required")
    return instance


def read_bundle(path):
    with Path(path).open("rb") as handle:
        return read_json(handle.read(4097))


def load_bundles():
    admin=read_bundle("/secrets/bootstrap/db.json")
    if (set(admin)!={"user","password","database"} or admin["user"]!="postgres"
            or admin["database"]!="order_queue" or not isinstance(admin["password"],str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}",admin["password"])):
        raise ValueError("invalid_bootstrap_bundle")
    roles=validate_bundles({role:read_bundle("/secrets/"+role+"/db.json")
                          for role in ("portal","worker","dispatcher")})
    return admin,roles


def execute(environ=None):
    env=os.environ if environ is None else environ
    instance=configuration(env)
    admin,roles=load_bundles()
    schema=(ROOT/"sql/schema.sql").read_text(encoding="utf-8")
    grants=(ROOT/"sql/roles.sql").read_text(encoding="utf-8")
    connector=Connector(ip_type=IPTypes.PRIVATE,refresh_strategy="LAZY",timeout=5,enable_iam_auth=False)
    def connect(value):
        return connector.connect(instance,"pg8000",user=value["user"],password=value["password"],
            db="order_queue",ip_type=IPTypes.PRIVATE,enable_iam_auth=False,timeout=5)
    try:
        connection=connect(admin)
        try:
            result=install(connection,roles,schema,grants)
        finally:
            connection.close()
        # Close the admin session first; then probe each real login sequentially.
        # A probe failure after commit is NOT permission to reset/recreate roles.
        for role in ("portal","worker","dispatcher"):
            connection=connect(roles[role])
            try:
                cursor=connection.cursor()
                try:
                    cursor.execute("SET LOCAL statement_timeout='3s'")
                    cursor.execute("SELECT current_user,current_database()")
                    if tuple(cursor.fetchone() or ())!=(roles[role]["user"],"order_queue"):
                        raise ValueError("runtime_login_binding_mismatch")
                    cursor.execute("SELECT version,seed_version FROM lab007.schema_meta WHERE singleton")
                    if tuple(cursor.fetchone() or ())!=(1,"catalog-v1"):
                        raise ValueError("runtime_schema_mismatch")
                    connection.rollback()
                finally:cursor.close()
            finally:connection.close()
        return {**result,"runtime_logins_checked":3}
    finally:
        connector.close()


def main():
    try:
        print(json.dumps({"component":"lab007-bootstrap",**execute()},sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"component":"lab007-bootstrap","event":"bootstrap_not_confirmed",
                          "next":"inspect_and_retry_same_bundles_no_reset"}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
