"""First-install transaction and read-only recheck. No migration, reset or password rotation."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re

USERS={"portal":("order_api",8),"worker":("order_worker",12),"dispatcher":("outbox_dispatcher",2)}
SELECT={
 "order_api":{"schema_meta","products","orders","order_items","outbox","processed_events","reservations","operator_actions"},
 "order_worker":{"schema_meta","products","orders","order_items","outbox","processed_events","reservations"},
 "outbox_dispatcher":{"schema_meta","orders","outbox"}}
INSERT={"order_api":{"orders","order_items","outbox","operator_actions"},
        "order_worker":{"processed_events","reservations"},"outbox_dispatcher":set()}
OPERATIONAL={"state","epoch","attempts","lease_token","lease_until","last_outcome","published_at"}
UPDATE={"order_api":{"outbox":OPERATIONAL},
        "outbox_dispatcher":{"outbox":OPERATIONAL},
        "order_worker":{"products":{"available"},"orders":{"state","safe_reason","finished_at"}}}
TABLES={"schema_meta","products","orders","order_items","outbox","processed_events","reservations",
        "operator_actions","bootstrap_receipt"}


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")


def validate_bundles(bundles):
    if not isinstance(bundles,dict) or set(bundles)!=set(USERS):
        raise ValueError("invalid_role_bundles")
    for role,(user,_) in USERS.items():
        value=bundles[role]
        if (not isinstance(value,dict) or set(value)!={"user","password","database"} or
                value["user"]!=user or value["database"]!="order_queue" or
                not isinstance(value["password"],str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}",value["password"])):
            raise ValueError("invalid_role_bundle")
    return json.loads(canonical(bundles))


def scram_verifier(password,*,salt=None):
    if not isinstance(password,str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}",password):
        raise ValueError("invalid_password")
    salt=os.urandom(16) if salt is None else salt
    if not isinstance(salt,bytes) or len(salt)!=16:
        raise ValueError("invalid_salt")
    salted=hashlib.pbkdf2_hmac("sha256",password.encode("ascii"),salt,4096)
    client_key=hmac.new(salted,b"Client Key","sha256").digest()
    stored=hashlib.sha256(client_key).digest()
    server=hmac.new(salted,b"Server Key","sha256").digest()
    encode=lambda value:base64.b64encode(value).decode("ascii")
    return "SCRAM-SHA-256$4096:"+encode(salt)+"$"+encode(stored)+":"+encode(server)


def statements(text):
    # Only these repository-owned static DDL files, without functions/quoted semicolons.
    # Refuse unsupported input instead of pretending this is a general SQL parser.
    if not isinstance(text,str) or len(text)>65536 or "$$" in text or "/*" in text:
        raise ValueError("unsupported_static_sql")
    value="\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    return [part.strip() for part in value.split(";") if part.strip()]


def verify_roles(cursor):
    names=tuple(user for user,_ in USERS.values())
    cursor.execute("""SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,
        rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname IN (%s,%s,%s)""",names)
    actual={value[0]:tuple(value[1:]) for value in cursor.fetchall()}
    expected={user:(True,False,False,False,False,False,limit) for user,limit in USERS.values()}
    if actual!=expected:
        raise ValueError("runtime_role_drift")
    cursor.execute("""SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
        WHERE r.rolname IN (%s,%s,%s)""",names)
    if cursor.fetchone()[0]!=0:
        raise ValueError("unexpected_runtime_membership")
    for user in names:
        cursor.execute("""SELECT has_schema_privilege(%s,'lab007','CREATE'),
            has_schema_privilege(%s,'public','CREATE'),has_database_privilege(%s,current_database(),'CREATE')""",
            (user,user,user))
        if any(cursor.fetchone()):
            raise ValueError("runtime_ddl_grant_drift")
        cursor.execute("""SELECT c.relname,pg_get_userbyid(c.relowner),
            has_table_privilege(%s,c.oid,'SELECT'),has_table_privilege(%s,c.oid,'INSERT'),
            has_table_privilege(%s,c.oid,'UPDATE'),has_table_privilege(%s,c.oid,'DELETE'),
            has_table_privilege(%s,c.oid,'TRUNCATE'),has_table_privilege(%s,c.oid,'REFERENCES'),
            has_table_privilege(%s,c.oid,'TRIGGER')
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='lab007' AND c.relkind IN ('r','p')""",(user,)*7)
        tables=cursor.fetchall()
        if {value[0] for value in tables}!=TABLES:
            raise ValueError("unexpected_schema_objects")
        for table,owner,*privileges in tables:
            if owner in names or tuple(privileges)!=(table in SELECT[user],table in INSERT[user],
                                                     False,False,False,False,False):
                raise ValueError("runtime_table_grant_drift")
        cursor.execute("""SELECT c.relname,a.attname,
            has_column_privilege(%s,c.oid,a.attnum,'SELECT'),
            has_column_privilege(%s,c.oid,a.attnum,'INSERT'),
            has_column_privilege(%s,c.oid,a.attnum,'UPDATE'),
            has_column_privilege(%s,c.oid,a.attnum,'REFERENCES')
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
            WHERE n.nspname='lab007' AND c.relkind IN ('r','p')""",(user,)*4)
        for table,column,*privileges in cursor.fetchall():
            expected=(table in SELECT[user],table in INSERT[user],
                      column in UPDATE[user].get(table,set()),False)
            if tuple(privileges)!=expected:
                raise ValueError("runtime_column_grant_drift")


def install(connection,bundles,schema_text,roles_text,*,expected_database="order_queue"):
    bundles=validate_bundles(bundles)
    manifest=hashlib.sha256(canonical({"schema":schema_text,"roles":roles_text,"installer":1})).hexdigest()
    credentials=hashlib.sha256(canonical(bundles)).hexdigest()
    cursor=connection.cursor()
    try:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        cursor.execute("SET LOCAL statement_timeout='10s'")
        cursor.execute("SET LOCAL lock_timeout='3s'")
        cursor.execute("SELECT current_database(),current_setting('server_version_num')::int")
        database,version=cursor.fetchone()
        if database!=expected_database or not 160000<=version<170000:
            raise ValueError("wrong_database_or_postgres_version")
        cursor.execute("SELECT pg_advisory_xact_lock(7007007)")
        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='lab007')")
        exists=cursor.fetchone()[0]
        if exists:
            cursor.execute("""SELECT manifest_sha256,credentials_sha256
                FROM lab007.bootstrap_receipt WHERE singleton""")
            receipt=cursor.fetchone()
            if tuple(receipt or ())!=(manifest,credentials):
                raise ValueError("existing_installation_mismatch_no_changes")
            cursor.execute("SELECT version,seed_version FROM lab007.schema_meta WHERE singleton")
            if tuple(cursor.fetchone() or ())!=(1,"catalog-v1"):
                raise ValueError("schema_version_mismatch_no_changes")
            verify_roles(cursor)
            disposition="already_installed"
        else:
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN (%s,%s,%s)",
                           tuple(user for user,_ in USERS.values()))
            if cursor.fetchall():
                raise ValueError("existing_runtime_roles_refused")
            for text in (schema_text,roles_text):
                for statement in statements(text):
                    cursor.execute(statement)
            cursor.execute("""CREATE TABLE lab007.bootstrap_receipt (
                singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
                manifest_sha256 text NOT NULL CHECK(manifest_sha256 ~ '^[a-f0-9]{64}$'),
                credentials_sha256 text NOT NULL CHECK(credentials_sha256 ~ '^[a-f0-9]{64}$'))""")
            cursor.execute("REVOKE ALL ON lab007.bootstrap_receipt FROM PUBLIC")
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            # Passwords never appear as raw SQL literals: only locally generated SCRAM verifiers.
            # Verifiers remain sensitive; do not enable statement/debug logging for bootstrap.
            for role,(user,_) in USERS.items():
                verifier=scram_verifier(bundles[role]["password"])
                if not re.fullmatch(r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+",verifier):
                    raise ValueError("invalid_generated_verifier")
                cursor.execute("ALTER ROLE "+user+" LOGIN PASSWORD '"+verifier+"'")
            cursor.execute("""INSERT INTO lab007.bootstrap_receipt
                (manifest_sha256,credentials_sha256) VALUES (%s,%s)""",(manifest,credentials))
            verify_roles(cursor)
            disposition="installed"
        connection.commit()
        return {"disposition":disposition,"schema_version":1,"seed_version":"catalog-v1",
                "manifest_sha256":manifest}
    except BaseException:
        connection.rollback()
        raise
    finally:
        cursor.close()
