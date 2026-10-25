"""Private Worker HTTP target contract tests; IAM is enforced by Cloud Run."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker import WorkerResult
from app.worker_api import create_worker_app


class FakeWorker:
    def __init__(self):
        self.calls = []

    def process(self, payload):
        self.calls.append(payload)
        return WorkerResult(503, {"error": "partner_temporarily_unavailable"}, {"Retry-After": "5"})


class WorkerApiTests(unittest.TestCase):
    def setUp(self):
        self.worker = FakeWorker()
        self.client = create_worker_app(worker=self.worker).test_client()
        self.valid = b'{"delivery_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","event_id":"550e8400-e29b-41d4-a716-446655440000","generation":1,"partner_id":"partner-a"}'

    def test_canonical_task_body_is_forwarded_and_retry_headers_preserved(self):
        response = self.client.post(
            "/internal/deliver",
            data=self.valid,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Retry-After"], "5")
        self.assertEqual(self.worker.calls, [{
            "delivery_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "event_id": "550e8400-e29b-41d4-a716-446655440000",
            "generation": 1,
            "partner_id": "partner-a",
        }])

    def test_non_json_malformed_and_noncanonical_bodies_are_rejected(self):
        self.assertEqual(self.client.post(
            "/internal/deliver", data=self.valid, content_type="text/plain"
        ).status_code, 415)
        self.assertEqual(self.client.post(
            "/internal/deliver", data=b"{bad", content_type="application/json"
        ).status_code, 400)
        self.assertEqual(self.client.post(
            "/internal/deliver",
            data=b'{ "delivery_id": "x" }',
            content_type="application/json",
        ).status_code, 400)
        self.assertEqual(self.worker.calls, [])

    def test_health_and_method_contract(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/internal/deliver").status_code, 405)


if __name__ == "__main__":
    unittest.main()
