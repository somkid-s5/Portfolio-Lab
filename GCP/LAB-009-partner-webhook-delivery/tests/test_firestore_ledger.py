"""Firestore transaction tests require the explicit loopback emulator."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import os
import sys
import threading
import unittest
import uuid
from pathlib import Path

from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import ValidationError, build_event, parse_submission, payload_sha256, task_resource_name
from app.ledger import FirestoreLedger, IdempotencyConflict, LedgerInvariantError


PROJECT = "demo-lab009"
PARTNERS = ("partner-a",)
BODY = (
    b'{"partner_id":"partner-a","order_ref":"ORD-AB12CD34",'
    b'"occurred_at":"2026-10-24T01:00:00Z","shipping_status":"shipped"}'
)
NOW = datetime(2026, 10, 24, 1, 2, 3, tzinfo=timezone.utc)


class FirestoreLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FIRESTORE_EMULATOR_HOST") != "127.0.0.1:8089":
            raise RuntimeError("explicit_loopback_emulator_required")
        cls.client = firestore.Client(
            project=PROJECT,
            database="lab09-ledger-tests",
            credentials=AnonymousCredentials(),
        )

    def setUp(self):
        self.prefix = "t_" + uuid.uuid4().hex[:20]
        self.now = NOW
        self.ledger = FirestoreLedger(
            self.client,
            collection_prefix=self.prefix,
            clock=lambda: self.now,
        )
        self.request_hash = payload_sha256(BODY)
        self.key = "lab09-idempotency-key-0001"

    def tearDown(self):
        for collection in (self.ledger.events, self.ledger.deliveries, self.ledger.idempotency):
            for snapshot in collection.stream(timeout=10):
                if collection is self.ledger.deliveries:
                    for attempt in snapshot.reference.collection("attempts").stream(timeout=10):
                        attempt.reference.delete(timeout=10)
                snapshot.reference.delete(timeout=10)

    def event(self, event_id=None):
        event_id = event_id or str(uuid.uuid4())
        return build_event(
            parse_submission(BODY, PARTNERS),
            event_id=event_id,
            accepted_at=NOW,
        )

    def task_name(self, event, generation=1):
        delivery = hashlib.sha256(
            f"{event['event_id']}:{event['partner_id']}".encode()
        ).hexdigest()
        return task_resource_name(
            PROJECT, "asia-southeast1", "partner-a", delivery, generation
        )

    def accept(self, event=None, *, key=None, request_hash=None):
        event = event or self.event()
        return self.ledger.accept(
            event,
            idempotency_key=key or self.key,
            request_sha256=request_hash or self.request_hash,
            task_name=self.task_name(event),
        )

    def test_accept_atomically_creates_event_delivery_and_hashed_key(self):
        event = self.event()
        result = self.accept(event)
        self.assertFalse(result.duplicate)
        stored_event = self.ledger.get_event(result.event_id)
        stored_delivery = self.ledger.get_delivery(result.delivery_id)
        stored_key = self.ledger.idempotency.document(
            hashlib.sha256(self.key.encode()).hexdigest()
        ).get(timeout=10).to_dict()

        self.assertEqual(stored_event["canonical_body"], self._canonical(event))
        self.assertEqual(stored_event["payload_sha256"], result.payload_sha256)
        self.assertEqual(stored_delivery["status"], "enqueue_pending")
        self.assertEqual(stored_delivery["generation"], 1)
        self.assertEqual(stored_delivery["event_id"], event["event_id"])
        self.assertEqual(stored_key["event_id"], event["event_id"])
        self.assertNotIn(self.key, str(stored_key))
        self.assertEqual(len(list(self.ledger.events.stream())), 1)
        self.assertEqual(len(list(self.ledger.deliveries.stream())), 1)
        self.assertEqual(len(list(self.ledger.idempotency.stream())), 1)

    def _canonical(self, event):
        from app.domain import canonical_event_bytes
        return canonical_event_bytes(event)

    def test_same_key_and_body_returns_original_event(self):
        first = self.accept(self.event())
        retry = self.accept(self.event())
        self.assertTrue(retry.duplicate)
        self.assertEqual(retry.event_id, first.event_id)
        self.assertEqual(retry.delivery_id, first.delivery_id)
        self.assertEqual(retry.payload_sha256, first.payload_sha256)
        self.assertEqual(len(list(self.ledger.events.stream())), 1)

    def test_same_key_with_different_body_hash_is_conflict(self):
        self.accept(self.event())
        with self.assertRaises(IdempotencyConflict):
            self.accept(self.event(), request_hash="a" * 64)
        self.assertEqual(len(list(self.ledger.events.stream())), 1)

    def test_concurrent_same_key_writes_only_one_event(self):
        barrier = threading.Barrier(2, timeout=15)

        def compete(_):
            event = self.event()
            barrier.wait()
            return self.accept(event)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(compete, range(2)))
        self.assertCountEqual([item.duplicate for item in outcomes], [False, True])
        self.assertEqual(outcomes[0].event_id, outcomes[1].event_id)
        self.assertEqual(len(list(self.ledger.events.stream())), 1)
        self.assertEqual(len(list(self.ledger.deliveries.stream())), 1)

    def test_task_enqueue_mark_is_idempotent_and_never_regresses_worker_state(self):
        event = self.event()
        result = self.accept(event)
        task_name = self.task_name(event)

        self.assertTrue(self.ledger.mark_task_enqueued(
            result.delivery_id, generation=1, task_name=task_name, now=NOW
        ))
        self.assertTrue(self.ledger.mark_task_enqueued(
            result.delivery_id, generation=1, task_name=task_name, now=NOW
        ))
        self.ledger.deliveries.document(result.delivery_id).update(
            {"status": "delivered", "updated_at": NOW}
        )
        self.assertFalse(self.ledger.mark_task_enqueued(
            result.delivery_id, generation=1, task_name=task_name, now=NOW
        ))
        self.assertEqual(self.ledger.get_delivery(result.delivery_id)["status"], "delivered")

    def test_stale_generation_cannot_mark_current_delivery_queued(self):
        event = self.event()
        result = self.accept(event)
        self.assertFalse(self.ledger.mark_task_enqueued(
            result.delivery_id, generation=2, task_name=self.task_name(event, generation=2), now=NOW
        ))
        with self.assertRaises(ValidationError):
            self.ledger.mark_task_enqueued(
                result.delivery_id, generation=1, task_name="wrong/task-name", now=NOW
            )
        self.assertEqual(self.ledger.get_delivery(result.delivery_id)["status"], "enqueue_pending")


    def test_enqueue_error_is_bounded_and_keeps_durable_outbox_pending(self):
        event = self.event()
        result = self.accept(event)
        self.assertTrue(self.ledger.record_enqueue_error(
            result.delivery_id, generation=1, error_code="DeadlineExceeded", now=NOW
        ))
        record = self.ledger.get_delivery(result.delivery_id)
        self.assertEqual(record["status"], "enqueue_pending")
        self.assertEqual(record["enqueue_attempts"], 1)
        self.assertEqual(record["last_enqueue_error"], "DeadlineExceeded")
        self.assertEqual(record["enqueue_pending_since"], NOW)
        self.assertFalse(self.ledger.record_enqueue_error(
            result.delivery_id, generation=2, error_code="DeadlineExceeded", now=NOW
        ))
        with self.assertRaises(ValidationError):
            self.ledger.record_enqueue_error(
                result.delivery_id, generation=1, error_code="token=secret", now=NOW
            )

    def test_unknown_task_outcome_requires_review_and_never_reopens_terminal_state(self):
        event = self.event()
        result = self.accept(event)
        self.assertTrue(self.ledger.mark_task_enqueued(
            result.delivery_id, generation=1, task_name=self.task_name(event), now=NOW
        ))
        reason = "task_missing_after_already_exists"
        self.assertTrue(self.ledger.mark_retry_ended_unknown(
            result.delivery_id, generation=1, reason=reason, now=NOW
        ))
        self.assertTrue(self.ledger.mark_retry_ended_unknown(
            result.delivery_id, generation=1, reason=reason, now=NOW
        ))
        record = self.ledger.get_delivery(result.delivery_id)
        self.assertEqual(record["status"], "retry_ended_unknown")
        self.assertTrue(record["review_required"])
        self.assertEqual(record["review_reason"], reason)
        self.ledger.deliveries.document(result.delivery_id).update(
            {"status": "delivered", "updated_at": NOW}
        )
        self.assertFalse(self.ledger.mark_retry_ended_unknown(
            result.delivery_id, generation=1, reason=reason, now=NOW
        ))

    def _claim(self, event, result, *, generation=1, token="a" * 32, now=NOW):
        return self.ledger.claim_attempt(
            result.delivery_id,
            event_id=event["event_id"],
            partner_id=event["partner_id"],
            generation=generation,
            lease_token=token,
            lease_until=now + timedelta(seconds=45),
            now=now,
        )

    def test_worker_claim_and_terminal_commit_are_atomic_and_auditable(self):
        event = self.event()
        accepted = self.accept(event)
        claim = self._claim(event, accepted)
        self.assertEqual((claim.outcome, claim.attempt_number), ("claimed", 1))
        self.assertEqual(
            self.ledger.get_delivery(accepted.delivery_id)["status"],
            "attempt_running",
        )
        self.assertTrue(self.ledger.finish_attempt(
            accepted.delivery_id,
            generation=1,
            attempt_number=1,
            lease_token="a" * 32,
            outcome="delivered",
            http_status=200,
            now=NOW + timedelta(seconds=1),
        ))
        record = self.ledger.get_delivery(accepted.delivery_id)
        attempt = self.ledger.deliveries.document(accepted.delivery_id).collection(
            "attempts"
        ).document("g001-a001").get(timeout=10).to_dict()
        self.assertEqual(record["status"], "delivered")
        self.assertEqual(record["attempt_count"], 1)
        self.assertEqual(attempt["status"], "delivered")
        self.assertEqual(attempt["http_status"], 200)
        self.assertEqual(self._claim(event, accepted).outcome, "terminal")

    def test_active_lease_blocks_duplicate_and_wrong_fence_cannot_finish(self):
        event = self.event()
        accepted = self.accept(event)
        self.assertEqual(self._claim(event, accepted).outcome, "claimed")
        busy = self._claim(event, accepted, token="b" * 32, now=NOW + timedelta(seconds=1))
        self.assertEqual(busy.outcome, "busy")
        self.assertFalse(self.ledger.finish_attempt(
            accepted.delivery_id,
            generation=1,
            attempt_number=1,
            lease_token="b" * 32,
            outcome="delivered",
            http_status=200,
            now=NOW + timedelta(seconds=2),
        ))
        self.assertEqual(
            self.ledger.get_delivery(accepted.delivery_id)["status"],
            "attempt_running",
        )

    def test_expired_lease_fences_old_worker_and_marks_prior_attempt(self):
        event = self.event()
        accepted = self.accept(event)
        first = self._claim(event, accepted)
        later = NOW + timedelta(seconds=46)
        second = self._claim(event, accepted, token="b" * 32, now=later)
        self.assertEqual((first.attempt_number, second.attempt_number), (1, 2))
        self.assertFalse(self.ledger.finish_attempt(
            accepted.delivery_id,
            generation=1,
            attempt_number=1,
            lease_token="a" * 32,
            outcome="delivered",
            http_status=200,
            now=later,
        ))
        old = self.ledger.deliveries.document(accepted.delivery_id).collection(
            "attempts"
        ).document("g001-a001").get(timeout=10).to_dict()
        self.assertEqual(old["status"], "lease_expired")
        self.assertEqual(
            self.ledger.get_delivery(accepted.delivery_id)["attempt_count"],
            2,
        )

    def test_unknown_delivery_can_resume_when_matching_task_arrives(self):
        event = self.event()
        accepted = self.accept(event)
        self.assertTrue(self.ledger.mark_retry_ended_unknown(
            accepted.delivery_id,
            generation=1,
            reason="queued_task_not_found",
            now=NOW,
        ))
        claim = self._claim(event, accepted)
        self.assertEqual(claim.outcome, "claimed")
        record = self.ledger.get_delivery(accepted.delivery_id)
        self.assertEqual(record["status"], "attempt_running")
        self.assertFalse(record["review_required"])
        self.assertEqual(record["last_review_reason"], "queued_task_not_found")

    def test_attempt_limit_moves_delivery_to_manual_review(self):
        event = self.event()
        accepted = self.accept(event)
        for number in range(1, 6):
            at = NOW + timedelta(seconds=number * 60)
            token = f"{number:032x}"
            claim = self._claim(event, accepted, token=token, now=at)
            self.assertEqual(claim.attempt_number, number)
            self.assertTrue(self.ledger.finish_attempt(
                accepted.delivery_id,
                generation=1,
                attempt_number=number,
                lease_token=token,
                outcome="retry",
                http_status=503,
                error_code="partner_http_503",
                now=at + timedelta(seconds=1),
            ))
        at = NOW + timedelta(minutes=6)
        limited = self._claim(event, accepted, token="f" * 32, now=at)
        self.assertEqual(limited.outcome, "review_required")
        record = self.ledger.get_delivery(accepted.delivery_id)
        self.assertEqual(record["status"], "retry_ended_unknown")
        self.assertEqual(record["review_reason"], "worker_attempt_limit")
        self.assertTrue(record["review_required"])

    def test_duplicate_key_with_corrupt_idempotency_reference_fails_closed(self):
        event = self.event()
        self.accept(event)
        ref = self.ledger.idempotency.document(hashlib.sha256(self.key.encode()).hexdigest())
        ref.update({"event_id": None})
        with self.assertRaises(LedgerInvariantError):
            self.accept(self.event())


if __name__ == "__main__":
    unittest.main()
