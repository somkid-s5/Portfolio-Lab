"""Flask contract tests for the deliberately public synthetic partner endpoint."""
from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import build_event, canonical_event_bytes, parse_submission, sign_webhook
from app.simulator import PartnerSimulator
from app.simulator_api import create_simulator_app


PARTNER = "partner-a"
SECRET = b"lab09-synthetic-hmac-secret-32-bytes!"
NOW = datetime(2026, 10, 24, 1, 2, 3, tzinfo=timezone.utc)
EVENT = build_event(
    parse_submission(
        b'{"partner_id":"partner-a","order_ref":"ORD-AB12CD34",'
        b'"occurred_at":"2026-10-24T01:00:00Z","shipping_status":"shipped"}',
        (PARTNER,),
    ),
    event_id="550e8400-e29b-41d4-a716-446655440000",
    accepted_at=NOW,
)
RAW = canonical_event_bytes(EVENT)


class MemoryReceipts:
    def __init__(self):
        self.rows = set()

    def create_or_compare(self, **fields):
        key = fields["event_id"]
        if key in self.rows:
            return SimpleNamespace(outcome="duplicate")
        self.rows.add(key)
        return SimpleNamespace(outcome="created")


class SimulatorApiTests(unittest.TestCase):
    def setUp(self):
        self.receipts = MemoryReceipts()
        simulator = PartnerSimulator(
            partner_id=PARTNER,
            secret=SECRET,
            receipt_store=self.receipts,
            clock=lambda: NOW,
        )
        self.client = create_simulator_app(simulator=simulator).test_client()

    def headers(self):
        timestamp = int(NOW.timestamp())
        return {
            "X-Event-ID": EVENT["event_id"],
            "X-Webhook-Timestamp": str(timestamp),
            "X-Webhook-Generation": "1",
            "X-Webhook-Attempt": "1",
            "X-Webhook-Signature": sign_webhook(
                SECRET,
                RAW,
                partner_id=PARTNER,
                timestamp=timestamp,
                generation=1,
                attempt_number=1,
            ),
        }

    def test_valid_hmac_request_reaches_receipt_store(self):
        response = self.client.post(
            "/v1/webhooks/partner-a",
            data=RAW,
            content_type="application/json",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "received")
        self.assertEqual(len(self.receipts.rows), 1)

    def test_public_route_does_not_accept_user_selected_fault_modes(self):
        response = self.client.post(
            "/v1/webhooks/partner-a?fault_mode=permanent-400",
            data=RAW,
            content_type="application/json",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.receipts.rows), 1)

    def test_wrong_route_content_type_and_oversize_are_rejected(self):
        self.assertEqual(self.client.post(
            "/v1/webhooks/partner-b",
            data=RAW,
            content_type="application/json",
            headers=self.headers(),
        ).status_code, 404)
        self.assertEqual(self.client.post(
            "/v1/webhooks/partner-a",
            data=RAW,
            content_type="text/plain",
            headers=self.headers(),
        ).status_code, 415)
        self.assertEqual(self.client.post(
            "/v1/webhooks/partner-a",
            data=b"x" * 8193,
            content_type="application/json",
            headers=self.headers(),
        ).status_code, 413)
        self.assertEqual(self.receipts.rows, set())

    def test_health_and_method_contract(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertEqual(self.client.get("/v1/webhooks/partner-a").status_code, 405)


if __name__ == "__main__":
    unittest.main()
