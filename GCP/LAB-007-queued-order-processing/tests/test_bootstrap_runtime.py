import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"bootstrap"))
spec=importlib.util.spec_from_file_location("bootstrap_runtime",LAB/"bootstrap/run.py")
runtime=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
ENV={"CLOUD_RUN_JOB":"lab007-bootstrap","SERVICE_ROLE":"bootstrap",
     "GOOGLE_CLOUD_PROJECT":"demo-lab007","SQL_INSTANCE_CONNECTION_NAME":"demo-lab007:asia-southeast1:lab007-orders",
     **{key:"1" for key in runtime.VERSIONS}}
ROLES={role:{"user":user,"database":"order_queue","password":"private_"+role+"_"+"x"*48}
       for role,user in (("portal","order_api"),("worker","order_worker"),("dispatcher","outbox_dispatcher"))}
ADMIN={"user":"postgres","password":"private_bootstrap_"+"x"*48,"database":"order_queue"}


class BootstrapRuntimeTests(unittest.TestCase):
    def test_only_attached_bootstrap_job_fixed_instance_numeric_versions_before_adc(self):
        for changes in ({"CLOUD_RUN_JOB":"other"},{"SERVICE_ROLE":"portal"},{"K_SERVICE":"lab007-portal"},
            {"PGHOST":"127.0.0.1"},{"GOOGLE_APPLICATION_CREDENTIALS":"/private/key"},
            {"BOOTSTRAP_SECRET_VERSION":"latest"},{"SQL_INSTANCE_CONNECTION_NAME":"other:region:instance"}):
            with patch.object(runtime,"Connector") as constructor,patch.object(runtime,"load_bundles") as load:
                with self.assertRaises(ValueError):runtime.execute({**ENV,**changes})
                constructor.assert_not_called()
                load.assert_not_called()

    def test_real_connector_contract_admin_closed_before_three_sequential_runtime_probes(self):
        events=[]
        connections=[]
        for user in ("postgres","order_api","order_worker","outbox_dispatcher"):
            con=Mock()
            con.close.side_effect=lambda user=user:events.append(("close",user))
            con.cursor.return_value.fetchone.side_effect=[(user,"order_queue"),(1,"catalog-v1")]
            connections.append(con)
        def connect(*args,**kwargs):
            user=kwargs["user"]
            events.append(("connect",user))
            return connections[("postgres","order_api","order_worker","outbox_dispatcher").index(user)]
        connector=Mock()
        connector.connect.side_effect=connect
        with patch.object(runtime,"Connector",return_value=connector) as factory, \
             patch.object(runtime,"load_bundles",return_value=(ADMIN,ROLES)), \
             patch.object(runtime,"install",return_value={"disposition":"installed","schema_version":1}) as installer:
            result=runtime.execute(ENV)
        self.assertEqual(result["runtime_logins_checked"],3)
        self.assertEqual(events,[("connect","postgres"),("close","postgres"),
            ("connect","order_api"),("close","order_api"),("connect","order_worker"),("close","order_worker"),
            ("connect","outbox_dispatcher"),("close","outbox_dispatcher")])
        factory.assert_called_once_with(ip_type=runtime.IPTypes.PRIVATE,refresh_strategy="LAZY",timeout=5,enable_iam_auth=False)
        for call in connector.connect.call_args_list:
            self.assertEqual(call.args,("demo-lab007:asia-southeast1:lab007-orders","pg8000"))
            self.assertEqual(call.kwargs["ip_type"],runtime.IPTypes.PRIVATE)
            self.assertFalse(call.kwargs["enable_iam_auth"])
            self.assertEqual(call.kwargs["timeout"],5)
            self.assertEqual(call.kwargs["db"],"order_queue")
        installer.assert_called_once()
        connector.close.assert_called_once()

    def test_probe_failure_after_install_closes_sessions_without_reinstall_or_reset(self):
        admin,portal=Mock(),Mock()
        portal.cursor.return_value.fetchone.return_value=("wrong_role","order_queue")
        connector=Mock()
        connector.connect.side_effect=[admin,portal]
        with patch.object(runtime,"Connector",return_value=connector), \
             patch.object(runtime,"load_bundles",return_value=(ADMIN,ROLES)), \
             patch.object(runtime,"install",return_value={"disposition":"already_installed"}) as installer:
            with self.assertRaisesRegex(ValueError,"runtime_login_binding"):
                runtime.execute(ENV)
        installer.assert_called_once()
        admin.close.assert_called_once()
        portal.close.assert_called_once()
        connector.close.assert_called_once()

    def test_cli_sanitizes_database_exceptions_and_private_verifiers(self):
        output=io.StringIO()
        with patch.object(runtime,"execute",side_effect=RuntimeError("private-password-SCRAM-verifier")), \
             patch("sys.stdout",output):
            self.assertEqual(runtime.main(),2)
        value=json.loads(output.getvalue())
        self.assertNotIn("private-password",output.getvalue())
        self.assertNotIn("SCRAM",output.getvalue())
        self.assertEqual(value["next"],"inspect_and_retry_same_bundles_no_reset")


if __name__=="__main__":
    unittest.main()
