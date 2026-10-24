"""Partner simulator tests cover HMAC freshness, dedupe and fixed fault modes."""
from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import ValidationError, build_event, canonical_event_bytes, parse_submission, sign_webhook
from app.simulator import PartnerSimulator


PARTNER = "partner-a"
SECRET = b"lab09-synthetic-hmac-secret-32-bytes!"
NOW = datetime(2026, 10, 24, 1, 2, 3, tzinfo=timezone.utc)
BODY = (
    b'{"partner_id":"partner-a","order_ref":"ORD-AB12CD34",'
    b'"occurred_at":"2026-10-24T01:00:00Z","shipping_status":"shipped"}'
)
EVENT = build_event(
    parse_submission(BODY, (PARTNER,)),
    event_id="550e8400-e29b-41d4-a716-446655440000",
    accepted_at=NOW,
)
RAW = canonical_event_bytes(EVENT)


class MemoryReceipts:
    def __init__(self):
        self.rows = {}

    def create_or_compare(self, *, partner_id, event_id, payload_sha256, received_at, attempt_number):
        key = (partner_id, event_id)
        existing = self.rows.get(key)
        if existing is None:
            self.rows[key] = payload_sha256
            return SimpleNamespace(outcome="created")
        if existing == payload_sha256:
            return SimpleNamespace(outcome="duplicate")
        return SimpleNamespace(outcome="conflict")


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.receipts = MemoryReceipts()
        self.simulator = self.make_simulator()

    def make_simulator(self, mode="normal"):
        return PartnerSimulator(
            partner_id=PARTNER,
            secret=SECRET,
            receipt_store=self.receipts,
            fault_mode=mode,
            clock=lambda: NOW,
        )

    def headers(self, *, attempt=1, timestamp=None, raw=RAW, signature=None):
        timestamp = int(NOW.timestamp()) if timestamp is None else timestamp
        return {
            "X-Event-ID": EVENT["event_id"],
            "X-Webhook-Timestamp": str(timestamp),
            "X-Webhook-Generation": "1",
            "X-Webhook-Attempt": str(attempt),
            "X-Webhook-Signature": signature or sign_webhook(
                SECRET,
                raw,
                partner_id=PARTNER,
                timestamp=timestamp,
                generation=1,
                attempt_number=attempt,
            ),
        }

    def call(self, *, mode=None, attempt=1, timestamp=None, raw=RAW, headers=None):
        simulator = self.make_simulator(mode) if mode else self.simulator
        return simulator.receive(
            raw,
            headers or self.headers(attempt=attempt, timestamp=timestamp, raw=raw),
        )

    def test_signed_event_creates_durable_receipt_and_same_hash_deduplicates(self):
        status, _, body = self.call()
        self.assertEqual((status, body["status"]), (200, "received"))
        status, _, body = self.call(attempt=2)
        self.assertEqual((status, body["status"]), (200, "duplicate"))
        self.assertEqual(len(self.receipts.rows), 1)

    def test_invalid_hmac_or_stale_timestamp_is_rejected_before_receipt(self):
        bad = self.headers(signature="v1=" + "0" * 64)
        self.assertEqual(self.call(headers=bad)[0], 401)
        stale = int(NOW.timestamp()) - 301
        self.assertEqual(self.call(timestamp=stale)[0], 401)
        self.assertEqual(self.receipts.rows, {})

    def test_changed_body_with_old_signature_is_rejected(self):
        changed_event = dict(EVENT, order_ref="ORD-CD34EF56")
        changed = canonical_event_bytes(changed_event)
        old_signature = self.headers(raw=RAW)
        self.assertEqual(self.call(raw=changed, headers=old_signature)[0], 401)
        self.assertEqual(self.receipts.rows, {})

    def test_noncanonical_body_is_rejected_even_if_valid_json(self):
        self.assertEqual(self.call(raw=RAW + b" ")[0], 400)
        self.assertEqual(self.receipts.rows, {})

    def test_fixed_transient_mode_fails_first_two_then_writes_receipt(self):
        self.assertEqual(self.call(mode="transient-503-first-two", attempt=1)[0], 503)
        self.assertEqual(self.call(mode="transient-503-first-two", attempt=2)[0], 503)
        self.assertEqual(self.call(mode="transient-503-first-two", attempt=3)[0], 200)
        self.assertEqual(len(self.receipts.rows), 1)

    def test_accept_then_lost_acknowledgement_replays_as_duplicate(self):
        self.assertEqual(self.call(mode="accept-then-503-on-first", attempt=1)[0], 503)
        status, _, body = self.call(mode="accept-then-503-on-first", attempt=2)
        self.assertEqual((status, body["status"]), (200, "duplicate"))
        self.assertEqual(len(self.receipts.rows), 1)

    def test_permanent_fault_does_not_create_receipt(self):
        self.assertEqual(self.call(mode="permanent-400")[0], 400)
        self.assertEqual(self.receipts.rows, {})

    def test_conflicting_existing_receipt_returns_409(self):
        self.receipts.rows[(PARTNER, EVENT["event_id"])] = "b" * 64
        self.assertEqual(self.call()[0], 409)

    def test_fault_mode_is_not_request_controlled_or_arbitrary(self):
        with self.assertRaises(ValidationError):
            self.make_simulator("anything-goes")


if __name__ == "__main__":
    unittest.main()
