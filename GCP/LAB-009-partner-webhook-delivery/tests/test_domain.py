"""Pure tests for Lab 09 schema, idempotency, signing and retry contracts."""
from datetime import datetime, timezone
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from domain import (
    MAX_REQUEST_BYTES,
    ReceiptConflict,
    ValidationError,
    build_event,
    canonical_event_bytes,
    classify_partner_status,
    compare_receipt,
    delivery_id,
    idempotency_document_id,
    parse_submission,
    payload_sha256,
    retry_after_seconds,
    sign_webhook,
    task_id,
    task_payload,
    task_resource_name,
    verify_webhook,
    webhook_signing_bytes,
)


PARTNERS = ("partner-a", "partner-b")
ACCEPTED_AT = datetime(2026, 10, 24, 1, 2, 3, tzinfo=timezone.utc)
EVENT_ID = "01234567-89ab-4cde-8fab-0123456789ab"
VALID_BODY = json.dumps(
    {
        "partner_id": "partner-a",
        "order_ref": "ORD-AB12CD34",
        "occurred_at": "2026-10-24T01:00:00Z",
        "shipping_status": "shipped",
    },
    separators=(",", ":"),
).encode("utf-8")


def make_event(body=VALID_BODY):
    submission = parse_submission(body, PARTNERS)
    return build_event(submission, event_id=EVENT_ID, accepted_at=ACCEPTED_AT)


class SubmissionTests(unittest.TestCase):
    def test_valid_request_builds_server_owned_event(self):
        event = make_event()
        self.assertEqual(event["event_id"], EVENT_ID)
        self.assertEqual(event["event_type"], "order.shipped")
        self.assertEqual(event["schema_version"], 1)
        self.assertEqual(event["accepted_at"], "2026-10-24T01:02:03.000000Z")
        self.assertEqual(event["occurred_at"], "2026-10-24T01:00:00.000000Z")
        self.assertEqual(event["shipping_status"], "shipped")

    def test_canonical_bytes_are_compact_and_key_order_independent(self):
        event = make_event()
        expected = canonical_event_bytes(event)
        reversed_event = dict(reversed(list(event.items())))
        self.assertEqual(canonical_event_bytes(reversed_event), expected)
        self.assertNotIn(b": ", expected)
        self.assertEqual(payload_sha256(expected), hashlib.sha256(expected).hexdigest())

    def test_canonical_boundary_rejects_noncanonical_or_wrongly_typed_values(self):
        event = make_event()
        for name, value in (
            ("schema_version", True),
            ("event_id", "NOT-A-UUID"),
            ("partner_id", "Partner A"),
            ("order_ref", "ord-lowercase"),
            ("accepted_at", "2026-10-24T01:02:03Z"),
        ):
            invalid = {**event, name: value}
            with self.subTest(field=name), self.assertRaises(ValidationError):
                canonical_event_bytes(invalid)

    def test_non_ascii_is_stable_utf8(self):
        event = make_event(VALID_BODY)
        self.assertIsInstance(canonical_event_bytes(event), bytes)

    def test_rejects_non_object_and_invalid_utf8(self):
        for body in (b"[]", b"null", b"\xff"):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                parse_submission(body, PARTNERS)

    def test_rejects_oversize_and_empty_body(self):
        for body in (b"", b" " * (MAX_REQUEST_BYTES + 1)):
            with self.subTest(size=len(body)), self.assertRaises(ValidationError):
                parse_submission(body, PARTNERS)

    def test_rejects_duplicate_json_keys(self):
        body = b'{"partner_id":"partner-a","partner_id":"partner-b","order_ref":"ORD-AB12CD34","occurred_at":"2026-10-24T01:00:00Z","shipping_status":"shipped"}'
        with self.assertRaises(ValidationError):
            parse_submission(body, PARTNERS)

    def test_rejects_missing_and_extra_fields(self):
        cases = [
            b'{"partner_id":"partner-a"}',
            VALID_BODY[:-1] + b',"callback_url":"https://example.invalid"}',
        ]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(ValidationError):
                parse_submission(body, PARTNERS)

    def test_rejects_unlisted_partner_and_bad_order_ref(self):
        cases = [
            VALID_BODY.replace(b"partner-a", b"partner-z"),
            VALID_BODY.replace(b"ORD-AB12CD34", b"ORD-bad"),
        ]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(ValidationError):
                parse_submission(body, PARTNERS)

    def test_rejects_wrong_status_and_non_utc_time(self):
        cases = [
            VALID_BODY.replace(b"shipped", b"pending"),
            VALID_BODY.replace(b"01:00:00Z", b"06:00:00+05:00"),
            VALID_BODY.replace(b"01:00:00Z", b"2026-10-24"),
        ]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(ValidationError):
                parse_submission(body, PARTNERS)

    def test_accepts_equivalent_utc_offset_and_normalizes(self):
        body = VALID_BODY.replace(b"01:00:00Z", b"01:00:00+00:00")
        normalized = parse_submission(body, PARTNERS)
        self.assertEqual(normalized["occurred_at"], "2026-10-24T01:00:00.000000Z")


class IdentityAndTaskTests(unittest.TestCase):
    def test_idempotency_key_is_hashed_not_stored_verbatim(self):
        key = "lab09-demo-key-0001"
        value = idempotency_document_id(key)
        self.assertEqual(value, hashlib.sha256(key.encode()).hexdigest())
        self.assertNotEqual(value, key)

    def test_rejects_unsafe_or_unbounded_idempotency_keys(self):
        for key in ("short", "key with space-0001", "x" * 129):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                idempotency_document_id(key)

    def test_task_name_is_deterministic_and_generation_scoped(self):
        did = delivery_id(EVENT_ID, "partner-a")
        self.assertEqual(did, hashlib.sha256(f"{EVENT_ID}:partner-a".encode()).hexdigest())
        self.assertEqual(task_id(did, 1), task_id(did, 1))
        self.assertNotEqual(task_id(did, 1), task_id(did, 2))
        name = task_resource_name("demo-lab", "asia-southeast1", "partner-a", did, 1)
        self.assertTrue(name.endswith(f"/tasks/{task_id(did, 1)}"))
        self.assertEqual(len(task_id(did, 1)), 37)

    def test_task_payload_contains_only_ids_and_generation(self):
        event = make_event()
        task = task_payload(event, delivery_id(EVENT_ID, "partner-a"), 2)
        self.assertEqual(set(task), {"event_id", "delivery_id", "partner_id", "generation"})
        self.assertNotIn("order_ref", task)
        self.assertNotIn("payload", task)

    def test_rejects_invalid_generation_and_resource_names(self):
        did = delivery_id(EVENT_ID, "partner-a")
        for generation in (0, -1, True):
            with self.subTest(generation=generation), self.assertRaises(ValidationError):
                task_id(did, generation)
        with self.assertRaises(ValidationError):
            task_resource_name("bad/project", "asia-southeast1", "partner-a", did, 1)


class WebhookContractTests(unittest.TestCase):
    def setUp(self):
        self.secret = b"s" * 32
        self.raw = canonical_event_bytes(make_event())
        self.args = dict(
            partner_id="partner-a",
            timestamp=1_792_808_640,
            generation=2,
            attempt_number=3,
        )

    def test_signature_verifies_only_for_exact_raw_request(self):
        sig = sign_webhook(self.secret, self.raw, **self.args)
        self.assertTrue(verify_webhook(self.secret, self.raw, sig, now=self.args["timestamp"], **self.args))
        self.assertFalse(verify_webhook(self.secret, self.raw + b" ", sig, now=self.args["timestamp"], **self.args))

    def test_signature_changes_with_generation_attempt_and_path_scope(self):
        original = webhook_signing_bytes(self.raw, **self.args)
        self.assertTrue(original.startswith(
            b"v1\nPOST\n/v1/webhooks/partner-a\n1792808640\n2\n3\n"
        ))
        for changed in (
            {**self.args, "generation": 3},
            {**self.args, "attempt_number": 4},
            {**self.args, "partner_id": "partner-b"},
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(original, webhook_signing_bytes(self.raw, **changed))

    def test_rejects_expired_future_and_short_secret(self):
        sig = sign_webhook(self.secret, self.raw, **self.args)
        self.assertFalse(verify_webhook(self.secret, self.raw, sig, now=self.args["timestamp"] + 301, **self.args))
        self.assertFalse(verify_webhook(self.secret, self.raw, sig, now=self.args["timestamp"] - 301, **self.args))
        with self.assertRaises(ValidationError):
            sign_webhook(b"short", self.raw, **self.args)

    def test_status_classification_preserves_retryable_codes(self):
        expected = {200: "success", 204: "success", 400: "permanent", 401: "permanent",
                    408: "transient", 429: "transient", 500: "transient", 503: "transient"}
        for code, classification in expected.items():
            with self.subTest(code=code):
                self.assertEqual(classify_partner_status(code), classification)

    def test_retry_after_is_bounded_and_only_delta_seconds_are_used(self):
        self.assertEqual(retry_after_seconds({"Retry-After": "120"}), 60)
        self.assertEqual(retry_after_seconds({"retry-after": "0"}), 1)
        self.assertEqual(retry_after_seconds({"Retry-After": "12"}), 12)
        self.assertIsNone(retry_after_seconds({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}))
        self.assertIsNone(retry_after_seconds({}))

    def test_receiver_receipt_deduplicates_same_hash_and_rejects_mismatch(self):
        digest = payload_sha256(self.raw)
        self.assertEqual(compare_receipt(digest, digest), "duplicate")
        with self.assertRaises(ReceiptConflict):
            compare_receipt(digest, "0" * 64)


if __name__ == "__main__":
    unittest.main()
