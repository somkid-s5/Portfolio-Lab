import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from werkzeug.exceptions import InternalServerError

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
from order_domain import event_bytes
from orders import Conflict, IntegrityFailure
from queue_http import create_worker,create_dispatcher

SUB="projects/demo-lab007/subscriptions/lab007-orders-worker"
EVENT="a"*32
ORDER="b"*32


def push(message_id="123"):
    return {"message":{"messageId":message_id,"data":base64.b64encode(
        event_bytes(EVENT,ORDER,"c"*64)).decode()},"subscription":SUB}


def drained(**extra):
    return {"status":200,"reason":"empty","claimed":0,"publish_acks":0,
            "finished":0,"exhausted":0,"integrity_blocked":0,"events":[],**extra}


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.repo=Mock()
        self.repo.process.return_value={"state":"confirmed","disposition":"processed"}
        self.health=Mock()
        self.app=create_worker(self.repo,SUB,database_health=self.health)
        self.client=self.app.test_client()
        self.print_patch=patch("builtins.print")
        self.output=self.print_patch.start()
        self.addCleanup(self.print_patch.stop)

    def test_worker_ack_after_confirmed_or_business_rejected_commit(self):
        for state in ("confirmed","rejected"):
            self.repo.process.return_value={"state":state,"disposition":"processed"}
            response=self.client.post("/events/orders",json=push())
            self.assertEqual(response.status_code,204)
            self.assertEqual(response.data,b"")
            self.assertEqual(len(response.headers["X-Request-ID"]),32)
            self.assertEqual(response.headers["Cache-Control"],"no-store")
        self.assertEqual(self.repo.process.call_count,2)

    def test_duplicate_event_with_new_broker_id_still_acks_existing_result(self):
        self.repo.process.return_value={"state":"confirmed","disposition":"duplicate"}
        for message_id in ("123","456"):
            self.assertEqual(self.client.post("/events/orders",json=push(message_id)).status_code,204)
        self.assertEqual(self.repo.process.call_args_list[0].args,
                         self.repo.process.call_args_list[1].args)

    def test_transient_integrity_and_unknown_outcome_are_not_success_acks(self):
        for error in (RuntimeError("private-secret"),IntegrityFailure("private-secret")):
            self.repo.process.side_effect=error
            response=self.client.post("/events/orders",json=push())
            self.assertEqual(response.status_code,503)
            self.assertNotIn("private-secret",response.get_data(as_text=True))
        self.repo.process.side_effect=None
        self.repo.process.return_value={"state":"accepted","disposition":"unknown"}
        self.assertEqual(self.client.post("/events/orders",json=push()).status_code,503)

    def test_framework_server_error_is_retryable_not_poison(self):
        self.repo.process.side_effect=InternalServerError(description="private-secret")
        response=self.client.post("/events/orders",json=push())
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json["error"],"dependency_unavailable")
        self.assertNotIn("private-secret",response.get_data(as_text=True))

    def test_poison_and_binding_conflict_are_nacks_not_business_rejection(self):
        value=push()
        value["message"]["data"]=base64.b64encode(json.dumps({"schema_version":99,"event_id":EVENT,
            "order_id":ORDER,"order_fingerprint":"c"*64}).encode()).decode()
        response=self.client.post("/events/orders",json=value)
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.json["error"],"unsupported_schema_version")
        self.repo.process.assert_not_called()
        self.repo.process.side_effect=Conflict("event_binding_mismatch")
        response=self.client.post("/events/orders",json=push())
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.json["error"],"event_binding_mismatch")

    def test_lab_retryable_fault_nacks_valid_delivery_before_database_write(self):
        app=create_worker(self.repo,SUB,database_health=self.health,
                          fault_mode="retryable_503")
        response=app.test_client().post("/events/orders",json=push())
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json["error"],"lab_fault_retryable")
        self.repo.process.assert_not_called()
        record=json.loads(self.output.call_args.args[0])
        self.assertEqual(record["outcome"],"lab_fault_retryable")

    def test_unknown_worker_fault_mode_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"invalid_worker_fault_mode"):
            create_worker(self.repo,SUB,database_health=self.health,fault_mode="drop_database")

    def test_body_mimetype_subscription_and_method_bounds(self):
        self.assertEqual(self.client.post("/events/orders",data=b"x"*65537,
                                         content_type="application/json").status_code,413)
        self.assertEqual(self.client.post("/events/orders",data=b"{}",
                                         content_type="text/plain").status_code,400)
        value=push()
        value["subscription"]="projects/other-project/subscriptions/other-sub"
        self.assertEqual(self.client.post("/events/orders",json=value).status_code,400)
        self.assertEqual(self.client.get("/events/orders").status_code,405)
        self.repo.process.assert_not_called()

    def test_logs_do_not_include_auth_body_query_or_exception(self):
        response=self.client.post("/events/orders?secret=private-secret",json=push(),
            headers={"Authorization":"Bearer private-secret","X-Request-ID":"private-secret"})
        self.assertEqual(response.status_code,204)
        lines=[call.args[0] for call in self.output.call_args_list]
        combined="\n".join(lines)
        self.assertNotIn("private-secret",combined)
        self.assertNotIn("schema_version",combined)
        record=json.loads(lines[-1])
        self.assertEqual(record["event_id"],EVENT)
        self.assertEqual(record["route"],"/events/orders")
        self.assertEqual(record["request_id"],response.headers["X-Request-ID"])

    def test_health_is_separate_from_live_and_config_is_checked(self):
        self.health.side_effect=RuntimeError("private-secret")
        self.assertEqual(self.client.get("/livez").status_code,200)
        response=self.client.get("/healthz")
        self.assertEqual(response.status_code,503)
        self.assertNotIn("private-secret",response.get_data(as_text=True))
        with self.assertRaises(ValueError):
            create_worker(self.repo,"https://attacker.example",database_health=self.health)

    def test_dispatcher_accepts_only_empty_control_input_and_sanitizes_output(self):
        dispatcher=Mock()
        dispatcher.drain.return_value=drained(token="private-secret")
        client=create_dispatcher(dispatcher,database_health=Mock()).test_client()
        response=client.post("/internal/outbox/drain",json={})
        self.assertEqual(response.status_code,200)
        self.assertNotIn("private-secret",response.get_data(as_text=True))
        self.assertNotIn("token",response.json)
        self.assertEqual(client.post("/internal/outbox/drain",
                                    json={"topic":"attacker"}).status_code,400)
        self.assertEqual(client.post("/internal/outbox/drain",data=b"x"*1025,
                                    content_type="application/json").status_code,413)
        self.assertEqual(dispatcher.drain.call_count,1)

    def test_dispatcher_quarantine_and_outcome_logs_have_safe_projection(self):
        dispatcher=Mock()
        dispatcher.drain.return_value=drained(integrity_blocked=1,events=[{
            "event_id":EVENT,"outcome":"integrity_blocked",
            "token":"private-secret","payload":"private-secret"}])
        client=create_dispatcher(dispatcher,database_health=Mock()).test_client()
        response=client.post("/internal/outbox/drain",json={})
        self.assertEqual(response.status_code,200)
        records=[json.loads(call.args[0]) for call in self.output.call_args_list]
        self.assertTrue(any(r.get("outcome")=="integrity_blocked" for r in records))
        self.assertEqual(records[-1]["integrity_blocked"],1)
        self.assertNotIn("private-secret",json.dumps(records))

    def test_dispatcher_unknown_and_bad_summary_are_not_success(self):
        dispatcher=Mock()
        client=create_dispatcher(dispatcher,database_health=Mock()).test_client()
        dispatcher.drain.return_value=drained(status=503,reason="publish_unconfirmed")
        self.assertEqual(client.post("/internal/outbox/drain",json={}).status_code,503)
        dispatcher.drain.return_value=drained(claimed=True)
        self.assertEqual(client.post("/internal/outbox/drain",json={}).status_code,503)
        dispatcher.drain.side_effect=RuntimeError("private-secret")
        response=client.post("/internal/outbox/drain",json={})
        self.assertEqual(response.status_code,503)
        self.assertNotIn("private-secret",response.get_data(as_text=True))


if __name__=="__main__":
    unittest.main()
