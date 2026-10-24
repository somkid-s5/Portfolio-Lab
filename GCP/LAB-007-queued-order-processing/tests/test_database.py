import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.sql.connector import Connector,IPTypes
from sqlalchemy.exc import TimeoutError as PoolTimeout

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
import database
import queue_runtime
from order_domain import event_bytes


def environment(role="worker"):
    return {"K_SERVICE":"lab007-"+role,"SERVICE_ROLE":role,
        "GOOGLE_CLOUD_PROJECT":"demo-lab007",
        "SQL_INSTANCE_CONNECTION_NAME":"demo-lab007:asia-southeast1:lab007-orders",
        "DB_SECRET_VERSION":"1","DB_SECRET_FILE":"/secrets/db/db.json"}


class DatabaseTests(unittest.TestCase):
    def test_secret_bundle_is_bounded_and_role_specific(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/"db.json"
            bundle={"user":"order_worker","password":"x"*43,"database":"order_queue"}
            file.write_text(json.dumps(bundle))
            self.assertEqual(database.read_credentials(file,"worker"),bundle)
            with self.assertRaises(ValueError):
                database.read_credentials(file,"portal")
            for changes in [{"host":"attacker"},{"password":"bad\npassword"},
                            {"database":"other"},{"user":"postgres"}]:
                file.write_text(json.dumps({**bundle,**changes}))
                with self.assertRaises(ValueError):
                    database.read_credentials(file,"worker")
            file.write_bytes(b"x"*4097)
            with self.assertRaises(ValueError):
                database.read_credentials(file,"worker")

    def test_invalid_runtime_configuration_fails_before_connector_or_file_access(self):
        variants=[]
        for key,value in [("K_SERVICE","other-service"),("SERVICE_ROLE","portal"),
                          ("DB_SECRET_VERSION","latest"),("DB_SECRET_FILE","/tmp/key.json"),
                          ("SQL_INSTANCE_CONNECTION_NAME","other:region:instance")]:
            variants.append({**environment(),key:value})
        for key in database.FORBIDDEN_ENV:
            variants.append({**environment(),key:"forbidden"})
        with patch.object(database,"Connector",autospec=True) as connector, \
             patch.object(database,"read_credentials",autospec=True) as read:
            for env in variants:
                with self.subTest(env_keys=list(env)),self.assertRaises(ValueError):
                    database.build_database("worker",environ=env)
            connector.assert_not_called()
            read.assert_not_called()

    def test_real_connector_signature_private_lazy_and_driver_kwargs(self):
        # Real constructor with anonymous credentials; connect is mocked, no API calls.
        connector=Connector(credentials=AnonymousCredentials(),ip_type=IPTypes.PRIVATE,
                            refresh_strategy="LAZY",timeout=5,enable_iam_auth=False)
        self.addCleanup(connector.close)
        bundle={"user":"order_worker","password":"x"*43,"database":"order_queue"}
        engine=Mock()
        with patch.object(database,"Connector",autospec=True,return_value=connector) as factory, \
             patch.object(database,"read_credentials",autospec=True,return_value=bundle), \
             patch.object(database,"make_pool",autospec=True,return_value=engine) as pool, \
             patch.object(connector,"connect",autospec=True,return_value=Mock()) as connect:
            result=database.build_database("worker",environ=environment())
            factory.assert_called_once_with(ip_type=IPTypes.PRIVATE,refresh_strategy="LAZY",
                                            timeout=5,enable_iam_auth=False)
            creator,size=pool.call_args.args
            self.assertEqual(size,2)
            creator()
            connect.assert_called_once_with(
                "demo-lab007:asia-southeast1:lab007-orders","pg8000",
                user="order_worker",password="x"*43,db="order_queue",
                ip_type=IPTypes.PRIVATE,enable_iam_auth=False,timeout=5)
            result.connect()
            engine.raw_connection.assert_called_once()

    def test_pool_options_do_not_embed_credentials_or_allow_overflow(self):
        creator=Mock()
        with patch.object(database,"create_engine",autospec=True) as engine:
            database.make_pool(creator,2)
            self.assertEqual(engine.call_args.args,("postgresql+pg8000://",))
            options=engine.call_args.kwargs
            self.assertEqual((options["pool_size"],options["max_overflow"],options["pool_timeout"]),
                             (2,0,2))
            self.assertTrue(options["hide_parameters"])
            self.assertTrue(options["pool_pre_ping"])
            self.assertEqual(options["pool_reset_on_return"],"rollback")
            self.assertNotIn("password",str(engine.call_args))
        for size in (True,0,3):
            with self.assertRaises(ValueError):
                database.make_pool(creator,size)

    def test_failed_pool_setup_closes_connector(self):
        with patch.object(database,"Connector",autospec=True) as factory, \
             patch.object(database,"read_credentials",return_value={
                 "user":"order_worker","password":"x"*43,"database":"order_queue"}), \
             patch.object(database,"make_pool",side_effect=RuntimeError("test-failure")):
            with self.assertRaises(RuntimeError):
                database.build_database("worker",environ=environment())
            factory.return_value.close.assert_called_once()

    def test_database_dispose_always_closes_connector(self):
        engine,connector=Mock(),Mock()
        engine.dispose.side_effect=RuntimeError("test-failure")
        with self.assertRaises(RuntimeError):
            database.Database(engine,connector).close()
        connector.close.assert_called_once()

    def test_worker_factory_uses_role_and_defers_database_queries(self):
        db,repo=Mock(),Mock()
        with patch.object(queue_runtime,"build_database",return_value=db) as build, \
             patch.object(queue_runtime,"Orders",return_value=repo), \
             patch.object(queue_runtime.atexit,"register") as register, \
             patch.dict(os.environ,{"GOOGLE_CLOUD_PROJECT":"demo-lab007"},clear=True):
            app=queue_runtime.build_worker()
            build.assert_called_once_with("worker")
            db.connect.assert_not_called()
            self.assertEqual(app.test_client().get("/livez").status_code,200)
            repo.health.assert_not_called()
            register.assert_called_once_with(db.close)

    def test_worker_factory_passes_private_retryable_fault_switch(self):
        db,repo=Mock(),Mock()
        subscription="projects/demo-lab007/subscriptions/lab007-orders-worker"
        with patch.object(queue_runtime,"build_database",return_value=db), \
             patch.object(queue_runtime,"Orders",return_value=repo), \
             patch.object(queue_runtime.atexit,"register"), \
             patch.dict(os.environ,{"GOOGLE_CLOUD_PROJECT":"demo-lab007",
                                   "LAB007_WORKER_FAULT_MODE":"retryable_503"},clear=True):
            app=queue_runtime.build_worker()
            payload={"subscription":subscription,"message":{"messageId":"ci-message",
                "data":base64.b64encode(event_bytes("a"*32,"b"*32,"c"*64)).decode("ascii")}}
            response=app.test_client().post("/events/orders",json=payload)
            self.assertEqual(response.status_code,503)
            repo.process.assert_not_called()

    def test_dispatcher_factory_owns_and_closes_its_resources(self):
        db,publisher=Mock(),Mock()
        with patch.object(queue_runtime,"build_database",return_value=db) as build, \
             patch.object(queue_runtime,"build_publisher",return_value=publisher), \
             patch.object(queue_runtime.atexit,"register") as register, \
             patch.dict(os.environ,{"GOOGLE_CLOUD_PROJECT":"demo-lab007"},clear=True):
            app=queue_runtime.build_dispatcher()
            build.assert_called_once_with("dispatcher")
            self.assertEqual(app.test_client().get("/livez").status_code,200)
            self.assertEqual(register.call_count,2)
            self.assertIs(app.extensions["lab007_publisher"],publisher)


if __name__=="__main__":
    unittest.main()
