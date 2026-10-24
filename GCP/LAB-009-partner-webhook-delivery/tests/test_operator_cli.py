"""Operator CLI contracts remain bounded and never print event or secret bytes."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from google.api_core.exceptions import NotFound

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.operator_cli import inspect_delivery, read_receipt


EVENT_ID = "123e4567-e89b-12d3-a456-426614174000"
BUCKET = "lab009-test123-partner-a-r"
HASH = "a" * 64


class OperatorCliTests(unittest.TestCase):
    def test_inspect_returns_only_allowlisted_metadata(self):
        ledger = Mock()
        ledger.get_delivery.return_value = {
            "event_id": EVENT_ID,
            "partner_id": "partner-a",
            "generation": 2,
            "status": "retry_ended_unknown",
            "canonical_body": b"private event body",
            "secret": "must-not-appear",
            "last_redrive_reason": "checked Cloud Tasks and receipt",
        }

        result = inspect_delivery(ledger, "b" * 64)

        self.assertEqual(result["event_id"], EVENT_ID)
        self.assertEqual(result["last_redrive_reason"], "checked Cloud Tasks and receipt")
        self.assertNotIn("canonical_body", result)
        self.assertNotIn("secret", result)
        self.assertIsNone(inspect_delivery(Mock(get_delivery=Mock(return_value=None)), "b" * 64))

    def test_receipt_lookup_returns_metadata_only(self):
        client = Mock()
        blob = client.bucket.return_value.blob.return_value
        blob.download_as_bytes.return_value = json.dumps({
            "event_id": EVENT_ID,
            "partner_id": "partner-a",
            "payload_sha256": HASH,
            "first_received_at": "2026-10-24T01:00:00Z",
            "first_attempt_number": 3,
            "raw_body": "must-not-appear",
            "signature": "must-not-appear",
        }).encode()

        result = read_receipt(
            client,
            bucket_name=BUCKET,
            partner_id="partner-a",
            event_id=EVENT_ID,
        )

        self.assertEqual(result["first_attempt_number"], 3)
        self.assertNotIn("raw_body", result)
        self.assertNotIn("signature", result)
        client.bucket.assert_called_once_with(BUCKET)
        client.bucket.return_value.blob.assert_called_once_with(
            f"events/partner-a/{EVENT_ID}.json"
        )

    def test_missing_receipt_is_distinct_from_negative_delivery_proof(self):
        client = Mock()
        client.bucket.return_value.blob.return_value.download_as_bytes.side_effect = NotFound("missing")
        result = read_receipt(
            client,
            bucket_name=BUCKET,
            partner_id="partner-a",
            event_id=EVENT_ID,
        )
        self.assertIsNone(result)

    def test_receipt_rejects_mismatched_identity_or_hash(self):
        client = Mock()
        blob = client.bucket.return_value.blob.return_value
        blob.download_as_bytes.return_value = json.dumps({
            "event_id": EVENT_ID,
            "partner_id": "partner-b",
            "payload_sha256": HASH,
            "first_received_at": "2026-10-24T01:00:00Z",
            "first_attempt_number": 1,
        }).encode()
        with self.assertRaises(ValueError):
            read_receipt(
                client,
                bucket_name=BUCKET,
                partner_id="partner-a",
                event_id=EVENT_ID,
            )


if __name__ == "__main__":
    unittest.main()
