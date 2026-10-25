"""Event API integration tests use the Firestore Emulator and a fake Tasks client."""
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
from app.api import create_event_app
from app.domain import task_resource_name
from app.ledger import FirestoreLedger
from app.task_queue import PartnerQueue


PROJECT = "demo-lab009"
BODY = (
    b'{"partner_id":"partner-a","order_ref":"ORD-AB12CD34",'
    b'"occurred_at":"2026-10-24T01:00:00Z","shipping_status":"shipped"}'
)
NOW = datetime(2026, 10, 24, 1, 2, 3, tzinfo=timezone.utc)
KEY = "lab09-api-idempotency-key-0001"
QUEUE = PartnerQueue(
    project_id=PROJECT,
    location_id="asia-southeast1",
    queue_id="partner-a",
    partner_id="partner-a",
    worker_url="https://worker-a-1234567890.asia-southeast1.run.app/internal/deliver",
    task_service_account="lab09-tasks@demo-lab009.iam.gserviceaccount.com",
    oidc_audience="https://worker-a-1234567890.asia-southeast1.run.app",
)


class FakeEnqueuer:
    def __init__(self):
        self.outcome = "created"
        self.error = None
        self.calls = []

    def enqueue(self, event, *, delivery, generation, config):
        self.calls.append((event, delivery, generation, config))
        if self.error:
            raise self.error
        return SimpleNamespace(
            task_name=task_resource_name(
                PROJECT, "asia-southeast1", "partner-a", delivery, generation
            ),
            outcome=self.outcome,
        )


class EventApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FIRESTORE_EMULATOR_HOST") != "127.0.0.1:8089":
            raise RuntimeError("explicit_loopback_emulator_required")
        cls.client = firestore.Client(
            project=PROJECT,
            database="lab09-api-tests",
            credentials=AnonymousCredentials(),
        )

    def setUp(self):
        self.prefix = "api_" + uuid.uuid4().hex[:20]
        self.ledger = FirestoreLedger(
            self.client, collection_prefix=self.prefix, clock=lambda: NOW
        )
        self.enqueuer = FakeEnqueuer()
        self.ids = iter(str(uuid.uuid4()) for _ in range(20))
        self.app = create_event_app(
            ledger=self.ledger,
            enqueuer=self.enqueuer,
            partner_queues={"partner-a": QUEUE},
            clock=lambda: NOW,
            event_id_factory=lambda: next(self.ids),
        )
        self.client_api = self.app.test_client()

    def tearDown(self):
        for collection in (self.ledger.events, self.ledger.deliveries, self.ledger.idempotency):
            for snapshot in collection.stream(timeout=10):
                snapshot.reference.delete(timeout=10)

    def post(self, body=BODY, key=KEY, content_type="application/json"):
        return self.client_api.post(
            "/v1/events",
            data=body,
            content_type=content_type,
            headers={"Idempotency-Key": key},
        )

    def test_durable_accept_returns_202_and_fast_path_queues(self):
        response = self.post()
        body = response.get_json()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(body["status"], "accepted")
        self.assertFalse(body["duplicate"])
        self.assertEqual(len(self.enqueuer.calls), 1)
        record = self.ledger.get_delivery(body["delivery_id"])
        self.assertEqual(record["status"], "queued")
        self.assertEqual(record["generation"], 1)

    def test_idempotent_replay_returns_original_and_does_not_reenqueue_queued_work(self):
        first = self.post()
        replay = self.post()
        self.assertEqual(first.status_code, 202)
        self.assertEqual(replay.status_code, 202)
        self.assertFalse(first.get_json()["duplicate"])
        self.assertTrue(replay.get_json()["duplicate"])
        self.assertEqual(first.get_json()["event_id"], replay.get_json()["event_id"])
        self.assertEqual(len(self.enqueuer.calls), 1)

    def test_same_key_different_raw_body_returns_409(self):
        self.assertEqual(self.post().status_code, 202)
        changed = BODY.replace(b"ORD-AB12CD34", b"ORD-CD34EF56")
        conflict = self.post(body=changed)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(len(self.enqueuer.calls), 1)

    def test_enqueue_exception_keeps_202_and_pending_outbox_for_reconciler(self):
        self.enqueuer.error = TimeoutError("deliberately hidden")
        response = self.post()
        self.assertEqual(response.status_code, 202)
        record = self.ledger.get_delivery(response.get_json()["delivery_id"])
        self.assertEqual(record["status"], "enqueue_pending")
        self.assertEqual(record["enqueue_attempts"], 1)
        self.assertEqual(record["last_enqueue_error"], "TimeoutError")

    def test_missing_after_already_exists_is_marked_unknown_not_recreated(self):
        self.enqueuer.outcome = "missing_after_already_exists"
        response = self.post()
        self.assertEqual(response.status_code, 202)
        record = self.ledger.get_delivery(response.get_json()["delivery_id"])
        self.assertEqual(record["status"], "retry_ended_unknown")
        self.assertTrue(record["review_required"])

    def test_invalid_content_type_or_schema_does_not_write_ledger(self):
        unsupported = self.post(content_type="text/plain")
        invalid = self.post(body=b'{"unexpected":"field"}')
        self.assertEqual(unsupported.status_code, 415)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(len(list(self.ledger.events.stream())), 0)
        self.assertEqual(self.enqueuer.calls, [])


if __name__ == "__main__":
    unittest.main()
