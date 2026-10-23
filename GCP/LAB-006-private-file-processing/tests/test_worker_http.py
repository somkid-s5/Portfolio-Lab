import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from worker_http import create_app

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


if __name__ == "__main__":
    unittest.main()
