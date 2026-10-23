import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from worker_http import create_app
from retry_dispatch import RetryDispatcher
from job_state import Conflict
from datetime import datetime, timezone

BUCKET = "lab006-test-incoming"
NAME = "incoming/" + "a"*32 + "/source.csv"


class WorkerHttpTests(unittest.TestCase):
    def setUp(self):
        self.processor = Mock()
        self.processor.run.return_value = {"status": 204, "reason": "succeeded"}
        self.logs = []
        self.health = Mock()
        self.app = create_app(self.processor, BUCKET,
                              metadata_health=self.health, emit=self.logs.append)
        self.client = self.app.test_client()
        self.headers = {"ce-specversion": "1.0",
                        "ce-type": "google.cloud.storage.object.v1.finalized",
                        "ce-id": "event-123",
                        "ce-source": f"//storage.googleapis.com/projects/_/buckets/{BUCKET}",
                        "ce-subject": f"objects/{NAME}"}
        self.data = {"bucket": BUCKET, "name": NAME, "generation": "123",
                     "timeCreated": "2026-01-01T00:00:00Z"}

    def send(self, **kwargs):
        return self.client.post("/events/storage", headers=self.headers,
                                json=self.data, **kwargs)

    def test_valid_event_dispatches_pinned_identity_and_acknowledges(self):
        response = self.send()
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.data, b"")
        args = self.processor.run.call_args.args
        self.assertEqual(args[:2], ("a"*32, "123"))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.logs[-1]["job_id"], "a"*32)
        self.assertEqual(len(response.headers["X-Request-ID"]), 32)

    def test_retryable_error_does_not_leak_payload_or_exception(self):
        self.processor.run.side_effect = RuntimeError("password=never-print")
        self.data["mediaLink"] = "https://example.invalid/?secret=never-print"
        response = self.send()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("never-print", response.get_data(as_text=True))
        self.assertNotIn("never-print", json.dumps(self.logs))

    def test_busy_and_transient_results_return_503_not_false_ack(self):
        self.processor.run.return_value = {"status": 503, "reason": "lease_busy"}
        response = self.send()
        self.assertEqual((response.status_code, response.json["error"]),
                         (503, "retry_event"))

    def test_foreign_and_invalid_events_do_not_reach_processor(self):
        self.data["bucket"] = "other-bucket"
        self.assertEqual(self.send().status_code, 204)
        self.processor.run.assert_not_called()
        self.data["bucket"] = BUCKET
        self.headers["ce-subject"] = "objects/wrong"
        self.assertEqual(self.send().status_code, 400)
        self.processor.run.assert_not_called()

    def test_body_limit_wrong_method_and_no_headers_fail_closed(self):
        self.assertEqual(self.client.post("/events/storage", data=b"x"*65537,
                                         content_type="application/json").status_code, 413)
        self.assertEqual(self.client.post("/events/storage", json=self.data).status_code, 400)
        self.assertEqual(self.client.get("/events/storage").status_code, 405)
        self.processor.run.assert_not_called()

    def test_health_failure_is_separate_from_process_liveness(self):
        self.health.side_effect = RuntimeError("secret dependency message")
        self.assertEqual(self.client.get("/healthz").status_code, 503)
        self.assertEqual(self.client.get("/livez").status_code, 200)
        self.assertNotIn("secret", json.dumps(self.logs))



    def test_manual_retry_dispatch_uses_stored_generation_and_finalized_time(self):
        jobs = Mock()
        time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        jobs.read_retry_dispatch.return_value = {
            "job_id": "a"*32, "input_generation": "123", "input_finalized_at": time}
        client = create_app(self.processor, BUCKET, retry_jobs=jobs,
                            emit=self.logs.append).test_client()
        response = client.post("/events/retry", json={"job_id": "a"*32, "epoch": 1})
        self.assertEqual(response.status_code, 204)
        jobs.read_retry_dispatch.assert_called_once_with("a"*32, 1)
        self.processor.run.assert_called_once_with("a"*32, "123", time)
        jobs.read_retry_dispatch.side_effect = Conflict("stale_epoch")
        self.assertEqual(client.post("/events/retry",
                                     json={"job_id": "a"*32, "epoch": 1}).status_code, 409)
        self.assertEqual(client.post("/events/retry",
                                     json={"job_id": "a"*32, "epoch": True}).status_code, 400)

    def test_dispatcher_binds_id_token_audience_and_never_reads_response_body(self):
        supplier, opener = Mock(return_value="identity.token"), Mock()
        response = Mock(status=204)
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        dispatch = RetryDispatcher("https://worker-123.asia-southeast1.run.app",
                                   supplier, opener=opener)
        self.assertTrue(dispatch("a"*32, 1))
        supplier.assert_called_once_with("https://worker-123.asia-southeast1.run.app")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer identity.token")
        self.assertEqual(json.loads(request.data), {"job_id": "a"*32, "epoch": 1})
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 10)
        response.read.assert_not_called()
        opener.open.side_effect = TimeoutError("uncertain delivery")
        self.assertFalse(dispatch("a"*32, 1))
        for url in ("http://worker.run.app", "https://evil.invalid",
                    "https://worker.run.app/?token=x"):
            with self.assertRaises(ValueError):
                RetryDispatcher(url, supplier)


if __name__ == "__main__":
    unittest.main()
