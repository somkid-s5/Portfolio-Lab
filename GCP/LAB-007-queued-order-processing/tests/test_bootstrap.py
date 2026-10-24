"""Isolated PG16 bootstrap tests. Uses a NON-superuser installer and real SCRAM logins."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import pg8000.dbapi

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
sys.path.insert(0,str(LAB/"bootstrap"))
from installer import install,scram_verifier,validate_bundles,statements
from order_domain import canonical,parse_event
from orders import Orders

DB="lab007_bootstrap_ci"
ROLE_PASSWORD="disposable-installer-ci"
BUNDLES={role:{"user":user,"database":"order_queue","password":"ci_"+role+"_"+"x"*48}
         for role,user in (("portal","order_api"),("worker","order_worker"),("dispatcher","outbox_dispatcher"))}


def connection(user=None,password=None):
    if (os.environ.get("LAB007_BOOTSTRAP_DISPOSABLE")!="1" or
            os.environ.get("PGHOST")!="127.0.0.1" or os.environ.get("PGDATABASE")!=DB):
        raise RuntimeError("isolated_loopback_bootstrap_database_required")
    return pg8000.dbapi.connect(host="127.0.0.1",port=int(os.environ["PGPORT"]),database=DB,
        user=user or os.environ["PGUSER"],password=password or os.environ["PGPASSWORD"],timeout=5)


def admin(sql,params=()):
    con=connection()
    try:
        cur=con.cursor()
        cur.execute(sql,params)
        result=cur.fetchall() if cur.description else None
        con.commit()
        cur.close()
        return result
    finally:con.close()


class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        admin("CREATE ROLE lab007_installer LOGIN CREATEDB CREATEROLE NOSUPERUSER PASSWORD 'disposable-installer-ci'")
        admin("ALTER DATABASE lab007_bootstrap_ci OWNER TO lab007_installer")

    def setUp(self):
        admin("DROP SCHEMA IF EXISTS lab007 CASCADE")
        for user in ("order_api","order_worker","outbox_dispatcher"):
            if admin("SELECT 1 FROM pg_roles WHERE rolname=%s",(user,)):
                admin("DROP OWNED BY "+user)
                admin("DROP ROLE "+user)
        self.schema=(LAB/"sql/schema.sql").read_text()
        self.roles=(LAB/"sql/roles.sql").read_text()

    def run_install(self,bundles=None,schema=None,roles=None,wrapper=None):
        con=connection("lab007_installer",ROLE_PASSWORD)
        try:
            return install(wrapper(con) if wrapper else con,
                BUNDLES if bundles is None else bundles,self.schema if schema is None else schema,
                self.roles if roles is None else roles,expected_database=DB)
        finally:con.close()

    def runtime(self,role):
        value=BUNDLES[role]
        return connection(value["user"],value["password"])

    def snapshots(self):
        return (admin("SELECT sku,available FROM lab007.products ORDER BY sku"),
            admin("SELECT rolname,rolpassword FROM pg_authid WHERE rolname IN ('order_api','order_worker','outbox_dispatcher') ORDER BY rolname"),
            admin("SELECT order_id,state,total_satang FROM lab007.orders ORDER BY order_id"))

    def test_first_install_is_nonsuperuser_atomic_and_all_real_scram_logins_work(self):
        result=self.run_install()
        self.assertEqual(result["disposition"],"installed")
        self.assertEqual(admin("SELECT rolsuper FROM pg_roles WHERE rolname='lab007_installer'")[0][0],False)
        for role in BUNDLES:
            con=self.runtime(role)
            try:
                cur=con.cursor()
                cur.execute("SELECT current_user,version,seed_version FROM lab007.schema_meta")
                self.assertEqual(cur.fetchone(),[BUNDLES[role]["user"],1,"catalog-v1"])
                cur.close()
                con.rollback()
            finally:con.close()
        self.assertEqual(admin("SELECT count(*) FROM lab007.products")[0][0],3)
        self.assertNotIn("password",json.dumps(result))
        self.assertNotIn("SCRAM",json.dumps(result))

    def test_rerun_after_business_transaction_preserves_password_stock_and_ledger(self):
        self.run_install()
        api=Orders(lambda:self.runtime("portal"))
        worker=Orders(lambda:self.runtime("worker"))
        order=api.create("alice",canonical({"idempotency_key":"a"*32,"items":[{"sku":"BOOK-01","quantity":2}]}))
        payload=admin("SELECT payload FROM lab007.outbox")[0][0].encode("ascii")
        worker.process(parse_event(payload))
        before=self.snapshots()
        self.assertEqual(self.run_install()["disposition"],"already_installed")
        self.assertEqual(self.snapshots(),before)
        self.assertEqual(admin("SELECT count(*) FROM lab007.processed_events")[0][0],1)
        self.assertEqual(api.read_owned("alice",order["order_id"])["state"],"confirmed")

    def test_new_password_bundle_is_refused_without_resetting_existing_logins(self):
        self.run_install()
        before=self.snapshots()
        changed=copy.deepcopy(BUNDLES)
        changed["portal"]["password"]="new_"+"z"*48
        with self.assertRaisesRegex(ValueError,"existing_installation_mismatch"):
            self.run_install(changed)
        self.assertEqual(self.snapshots(),before)
        con=self.runtime("portal")
        con.close()
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            connection("order_api",changed["portal"]["password"])

    def test_changed_ddl_or_existing_schema_without_receipt_is_not_adopted(self):
        self.run_install()
        before=self.snapshots()
        with self.assertRaisesRegex(ValueError,"existing_installation_mismatch"):
            self.run_install(schema=self.schema+"\n-- different release\n")
        self.assertEqual(self.snapshots(),before)
        admin("DROP TABLE lab007.bootstrap_receipt")
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            self.run_install()
        self.assertEqual(self.snapshots(),before)

    def test_partial_first_install_rolls_back_schema_roles_and_seed(self):
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            self.run_install(roles=self.roles+"\nSELECT missing_bootstrap_object;\n")
        self.assertFalse(admin("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='lab007')")[0][0])
        self.assertEqual(admin("SELECT count(*) FROM pg_roles WHERE rolname IN ('order_api','order_worker','outbox_dispatcher')")[0][0],0)
        self.assertEqual(self.run_install()["disposition"],"installed")

    def test_unknown_commit_resolves_by_same_manifest_and_bundle_without_reset(self):
        class LostCommit:
            def __init__(self,con):self.con=con
            def cursor(self):return self.con.cursor()
            def commit(self):
                self.con.commit()
                raise TimeoutError("intentional_reply_lost_after_commit")
            def rollback(self):return self.con.rollback()
        with self.assertRaises(TimeoutError):
            self.run_install(wrapper=LostCommit)
        before=self.snapshots()
        self.assertEqual(self.run_install()["disposition"],"already_installed")
        self.assertEqual(self.snapshots(),before)

    def test_concurrent_bootstraps_have_one_install_and_one_readonly_recheck(self):
        barrier=threading.Barrier(2)
        def run(_):
            barrier.wait(timeout=10)
            return self.run_install()["disposition"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(run,range(2),timeout=45))
        self.assertEqual(sorted(values),["already_installed","installed"])
        self.assertEqual(admin("SELECT count(*) FROM lab007.bootstrap_receipt")[0][0],1)

    def test_preexisting_runtime_role_without_schema_is_never_modified(self):
        admin("CREATE ROLE order_api NOLOGIN")
        with self.assertRaisesRegex(ValueError,"existing_runtime_roles_refused"):
            self.run_install()
        self.assertEqual(admin("SELECT rolcanlogin FROM pg_roles WHERE rolname='order_api'")[0][0],False)
        self.assertFalse(admin("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='lab007')")[0][0])

    def test_role_and_table_grant_drift_is_reported_not_silently_repaired(self):
        self.run_install()
        before=self.snapshots()
        admin("GRANT DELETE ON lab007.reservations TO order_api")
        with self.assertRaisesRegex(ValueError,"runtime_table_grant_drift"):
            self.run_install()
        self.assertEqual(self.snapshots(),before)
        self.assertTrue(admin("SELECT has_table_privilege('order_api','lab007.reservations','DELETE')")[0][0])

    def test_credentials_and_static_parser_reject_unsupported_inputs(self):
        for bundles in ({},{**BUNDLES,"admin":{}},
            {**BUNDLES,"portal":{**BUNDLES["portal"],"user":"postgres"}},
            {**BUNDLES,"worker":{**BUNDLES["worker"],"password":"bad'quote"}}):
            with self.assertRaises(ValueError):validate_bundles(bundles)
        for text in ("/* comment */ SELECT 1;","DO $$ BEGIN END $$;"):
            with self.assertRaises(ValueError):statements(text)
        first=scram_verifier("p"*48,salt=b"x"*16)
        self.assertTrue(first.startswith("SCRAM-SHA-256$4096:"))
        self.assertNotIn("p"*48,first)
        self.assertNotEqual(scram_verifier("p"*48),scram_verifier("p"*48))

    def test_preexisting_public_application_table_is_preserved_and_install_refused(self):
        admin("CREATE TABLE public.bootstrap_ci_existing (id integer PRIMARY KEY)")
        self.addCleanup(lambda:admin("DROP TABLE public.bootstrap_ci_existing"))
        admin("INSERT INTO public.bootstrap_ci_existing VALUES (17)")
        with self.assertRaisesRegex(ValueError,"existing_public_application_objects_refused"):
            self.run_install()
        self.assertEqual(admin("SELECT id FROM public.bootstrap_ci_existing"),[[17]])
        self.assertFalse(admin("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='lab007')")[0][0])
        self.assertEqual(admin("SELECT count(*) FROM pg_roles WHERE rolname IN ('order_api','order_worker','outbox_dispatcher')")[0][0],0)


if __name__=="__main__":
    unittest.main()
