"""Delivery Worker integration tests use Firestore Emulator and an HTTP double."""
from datetime import datetime, timezone
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import (
    build_event,
    delivery_id,
    parse_submission,
    task_payload,
    task_resource_name,
)
from app.ledger import FirestoreLedger
from app.worker import DeliveryWorker, PartnerEndpoint


PROJECT = "demo-lab009"
SECRET = b"lab09-synthetic-hmac-secret-32-bytes!"
BODY = (
    b'{"partner_id":"partner-a","order_ref":"ORD-AB12CD34",'
    b'"occurred_at":"2026-10-24T01:00:00Z","shipping_status":"shipped"}'
)
NOW = datetime(2026, 10, 24, 1, 2, 3, tzinfo=timezone.utc)
ENDPOINT = PartnerEndpoint(
    partner_id="partner-a",
    url="https://simulator-a-1234567890.asia-southeast1.run.app/v1/webhooks/partner-a",
    secret_version="projects/demo-lab009/secrets/partner-a-hmac/versions/1",
)


class FakeHttpSession:
    def __init__(self, status_code=200, headers=None, error=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.error = error
        self.calls = []

    def post(self, url, *, data, headers, timeout, allow_redirects):
        self.calls.append({
            "url": url,
            "data": data,
            "headers": headers,
            "timeout": timeout,
            "allow_redirects": allow_redirects,
        })
        if self.error:
            raise self.error
        return SimpleNamespace(status_code=self.status_code, headers=self.headers)


class DeliveryWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FIRESTORE_EMULATOR_HOST") != "127.0.0.1:8089":
            raise RuntimeError("explicit_loopback_emulator_required")
        cls.client = firestore.Client(
            project=PROJECT,
            database="lab09-worker-tests",
            credentials=AnonymousCredentials(),
        )

    def setUp(self):
        self.prefix = "worker_" + uuid.uuid4().hex[:18]
        self.ledger = FirestoreLedger(
            self.client, collection_prefix=self.prefix, clock=lambda: NOW
        )
        self.event = build_event(
            parse_submission(BODY, ("partner-a",)),
            event_id=str(uuid.uuid4()),
            accepted_at=NOW,
        )
        self.delivery = delivery_id(self.event["event_id"], "partner-a")
        self.ledger.accept(
            self.event,
            idempotency_key="lab09-worker-" + uuid.uuid4().hex,
            request_sha256="a" * 64,
            task_name=task_resource_name(
                PROJECT, "asia-southeast1", "partner-a", self.delivery, 1
            ),
        )
        self.http = FakeHttpSession()
        self.worker = self.make_worker()

    def make_worker(self, *, endpoints=None, secret_provider=None, http=None):
        return DeliveryWorker(
            ledger=self.ledger,
            partner_endpoints=endpoints or {"partner-a": ENDPOINT},
            secret_provider=secret_provider or (lambda _version: SECRET),
            http_session=http or self.http,
            clock=lambda: NOW,
        )

    def tearDown(self):
        for collection in (self.ledger.events, self.ledger.deliveries, self.ledger.idempotency):
            for snapshot in collection.stream(timeout=10):
                if collection is self.ledger.deliveries:
                    for attempt in snapshot.reference.collection("attempts").stream(timeout=10):
                        attempt.reference.delete(timeout=10)
                snapshot.reference.delete(timeout=10)

    def payload(self, generation=1):
        return task_payload(self.event, self.delivery, generation)

    def test_success_signs_canonical_event_and_commits_before_ack(self):
        result = self.worker.process(self.payload())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.body["status"], "delivered")
        self.assertEqual(len(self.http.calls), 1)
        call = self.http.calls[0]
        self.assertEqual(call["data"], self.ledger.get_event(self.event["event_id"])["canonical_body"])
        self.assertEqual(call["timeout"], (5, 5))
        self.assertFalse(call["allow_redirects"])
        self.assertEqual(call["headers"]["X-Webhook-Attempt"], "1")
        self.assertTrue(call["headers"]["X-Webhook-Signature"].startswith("v1="))
        record = self.ledger.get_delivery(self.delivery)
        self.assertEqual(record["status"], "delivered")
        attempt = self.ledger.deliveries.document(self.delivery).collection(
            "attempts"
        ).document("g001-a001").get(timeout=10).to_dict()
        self.assertEqual(attempt["status"], "delivered")
        self.assertEqual(attempt["http_status"], 200)

    def test_429_is_recorded_then_returned_with_bounded_retry_after(self):
        self.http.status_code = 429
        self.http.headers = {"Retry-After": "120"}
        result = self.worker.process(self.payload())
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.headers, {"Retry-After": "60"})
        record = self.ledger.get_delivery(self.delivery)
        self.assertEqual(record["status"], "queued")
        self.assertEqual(record["last_attempt_outcome"], "retry")
        attempt = self.ledger.deliveries.document(self.delivery).collection(
            "attempts"
        ).document("g001-a001").get(timeout=10).to_dict()
        self.assertEqual(attempt["retry_after_seconds"], 60)

    def test_permanent_partner_4xx_is_terminal_and_acknowledged(self):
        self.http.status_code = 422
        result = self.worker.process(self.payload())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.ledger.get_delivery(self.delivery)["status"], "permanent_failed")
        self.assertEqual(
            self.ledger.get_delivery(self.delivery)["last_error_code"],
            "partner_http_422",
        )

    def test_network_exception_releases_lease_for_cloud_tasks_retry(self):
        self.http.error = TimeoutError("do not persist")
        result = self.worker.process(self.payload())
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.headers, {"Retry-After": "5"})
        record = self.ledger.get_delivery(self.delivery)
        self.assertEqual(record["status"], "queued")
        self.assertEqual(record["last_error_code"], "TimeoutError")
        self.assertNotIn("do not persist", str(record))

    def test_terminal_duplicate_does_not_call_partner_twice(self):
        first = self.worker.process(self.payload())
        second = self.worker.process(self.payload())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.body["status"], "already_terminal")
        self.assertEqual(len(self.http.calls), 1)

    def test_active_fenced_worker_returns_retryable_busy(self):
        self.ledger.claim_attempt(
            self.delivery,
            event_id=self.event["event_id"],
            partner_id="partner-a",
            generation=1,
            lease_token="e" * 32,
            lease_until=NOW.replace(second=48),
            now=NOW,
        )
        result = self.worker.process(self.payload())
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.headers, {"Retry-After": "5"})
        self.assertEqual(self.http.calls, [])

    def test_stale_generation_is_acknowledged_without_partner_call(self):
        result = self.worker.process(self.payload(generation=2))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.body["status"], "superseded_generation")
        self.assertEqual(self.http.calls, [])

    def test_secret_provider_failure_is_retryable_and_bounded(self):
        self.worker = self.make_worker(
            secret_provider=lambda _version: (_ for _ in ()).throw(TimeoutError("hidden"))
        )
        result = self.worker.process(self.payload())
        self.assertEqual(result.status_code, 503)
        record = self.ledger.get_delivery(self.delivery)
        self.assertEqual(record["status"], "queued")
        self.assertEqual(record["last_error_code"], "TimeoutError")
        self.assertEqual(self.http.calls, [])

    def test_forbidden_secret_version_is_terminal_until_configuration_change(self):
        from app.secret_manager import SecretConfigurationError
        self.worker = self.make_worker(
            secret_provider=lambda _version: (_ for _ in ()).throw(
                SecretConfigurationError("secret detail hidden")
            )
        )
        result = self.worker.process(self.payload())
        self.assertEqual(result.status_code, 200)
        record = self.ledger.get_delivery(self.delivery)
        self.assertEqual(record["status"], "permanent_failed")
        self.assertEqual(record["last_error_code"], "SecretConfigurationError")
        self.assertEqual(self.http.calls, [])

    def test_missing_partner_configuration_is_recorded_as_permanent(self):
        other = PartnerEndpoint(
            partner_id="partner-b",
            url="https://simulator-b-1234567890.asia-southeast1.run.app/v1/webhooks/partner-b",
            secret_version="projects/demo-lab009/secrets/partner-b-hmac/versions/1",
        )
        self.worker = self.make_worker(endpoints={"partner-b": other})
        result = self.worker.process(self.payload())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.ledger.get_delivery(self.delivery)["status"], "permanent_failed")
        self.assertEqual(self.http.calls, [])

    def test_invalid_task_payload_never_claims_a_delivery(self):
        result = self.worker.process({"delivery_id": self.delivery, "generation": True})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.ledger.get_delivery(self.delivery)["status"], "enqueue_pending")


if __name__ == "__main__":
    unittest.main()
