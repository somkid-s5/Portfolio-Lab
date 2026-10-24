"""Bounded reconciliation tests run against Firestore Emulator and a task double."""
from datetime import datetime, timedelta, timezone
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import ValidationError, build_event, delivery_id, parse_submission, payload_sha256, task_resource_name
from app.ledger import FirestoreLedger
from app.reconciler import OutboxReconciler, STALE_ENQUEUE_AFTER
from app.task_queue import PartnerQueue


PROJECT = "demo-lab009"
BODY = (
    b'{"partner_id":"partner-a","order_ref":"ORD-AB12CD34",'
    b'"occurred_at":"2026-10-24T01:00:00Z","shipping_status":"shipped"}'
)
NOW = datetime(2026, 10, 24, 1, 2, 3, tzinfo=timezone.utc)
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
        self.calls = []
        self.exists = True

    def enqueue(self, event, *, delivery, generation, config):
        self.calls.append((event, delivery, generation, config))
        name = task_resource_name(
            config.project_id, config.location_id, config.queue_id, delivery, generation
        )
        return SimpleNamespace(task_name=name, outcome="created")

    def task_exists(self, task_name):
        return self.exists


class OutboxReconcilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FIRESTORE_EMULATOR_HOST") != "127.0.0.1:8089":
            raise RuntimeError("explicit_loopback_emulator_required")
        cls.client = firestore.Client(
            project=PROJECT,
            database="lab09-reconciler-tests",
            credentials=AnonymousCredentials(),
        )

    def setUp(self):
        self.prefix = "rec_" + uuid.uuid4().hex[:20]
        self.clock = NOW
        self.ledger = FirestoreLedger(
            self.client, collection_prefix=self.prefix, clock=lambda: self.clock
        )
        self.enqueuer = FakeEnqueuer()
        self.reconciler = OutboxReconciler(
            ledger=self.ledger,
            enqueuer=self.enqueuer,
            partner_queues={"partner-a": QUEUE},
            clock=lambda: self.clock,
        )

    def tearDown(self):
        for collection in (self.ledger.events, self.ledger.deliveries, self.ledger.idempotency):
            for snapshot in collection.stream(timeout=10):
                snapshot.reference.delete(timeout=10)

    def accept(self, number):
        event = build_event(
            parse_submission(BODY, ("partner-a",)),
            event_id=str(uuid.uuid4()),
            accepted_at=NOW,
        )
        did = delivery_id(event["event_id"], "partner-a")
        return self.ledger.accept(
            event,
            idempotency_key=f"lab09-reconcile-key-{number:04d}",
            request_sha256=payload_sha256(BODY),
            task_name=task_resource_name(
                PROJECT, "asia-southeast1", "partner-a", did, 1
            ),
        )

    def test_repairs_fresh_pending_outbox_deterministically(self):
        result = self.accept(1)
        summary = self.reconciler.run_once(page_size=2)
        self.assertEqual(summary.pending_seen, 1)
        self.assertEqual(summary.enqueued, 1)
        self.assertEqual(len(self.enqueuer.calls), 1)
        self.assertEqual(self.ledger.get_delivery(result.delivery_id)["status"], "queued")

    def test_stale_pending_deadline_uses_first_pending_time_not_last_error(self):
        result = self.accept(2)
        self.assertTrue(self.ledger.record_enqueue_error(
            result.delivery_id,
            generation=1,
            error_code="DeadlineExceeded",
            now=NOW + timedelta(minutes=14),
        ))
        self.assertEqual(
            self.ledger.get_delivery(result.delivery_id)["enqueue_pending_since"],
            NOW,
        )
        self.clock = NOW + STALE_ENQUEUE_AFTER + timedelta(seconds=1)
        summary = self.reconciler.run_once(page_size=2)
        self.assertEqual(summary.moved_to_review, 1)
        self.assertEqual(self.enqueuer.calls, [])
        record = self.ledger.get_delivery(result.delivery_id)
        self.assertEqual(record["status"], "retry_ended_unknown")
        self.assertEqual(record["review_reason"], "enqueue_pending_timeout")

    def test_missing_queued_task_moves_nonterminal_delivery_to_review(self):
        event_result = self.accept(3)
        record = self.ledger.get_delivery(event_result.delivery_id)
        task_name = record["task_name"]
        self.assertTrue(self.ledger.mark_task_enqueued(
            event_result.delivery_id, generation=1, task_name=task_name, now=NOW
        ))
        self.enqueuer.exists = False
        summary = self.reconciler.run_once(page_size=2)
        self.assertEqual(summary.queued_seen, 1)
        self.assertEqual(summary.moved_to_review, 1)
        self.assertEqual(self.enqueuer.calls, [])
        self.assertEqual(
            self.ledger.get_delivery(event_result.delivery_id)["status"],
            "retry_ended_unknown",
        )

    def test_one_event_lookup_failure_does_not_abort_the_bounded_page(self):
        self.accept(40)
        self.accept(41)
        original_get_event = self.ledger.get_event
        calls = {"count": 0}

        def fail_once(event_id):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("emulator_read_timeout")
            return original_get_event(event_id)

        self.ledger.get_event = fail_once
        summary = self.reconciler.run_once(page_size=4)
        self.assertEqual(summary.pending_seen, 2)
        self.assertEqual(summary.errors, 1)
        self.assertEqual(summary.enqueued, 1)
        self.assertEqual(len(self.enqueuer.calls), 1)

    def test_total_read_page_is_bounded(self):
        for number in range(4, 9):
            self.accept(number)
        summary = self.reconciler.run_once(page_size=3)
        self.assertLessEqual(summary.pending_seen + summary.queued_seen, 3)
        self.assertEqual(summary.pending_seen, 2)

    def test_page_size_above_contract_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.reconciler.run_once(page_size=26)


if __name__ == "__main__":
    unittest.main()
