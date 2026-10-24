"""Cloud Storage receipt adapter tests use a fake bucket and enforce create-only writes."""
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from google.api_core.exceptions import NotFound, PreconditionFailed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.receipt_store import CloudStorageReceiptStore


NOW = datetime(2026, 10, 24, 1, 2, 3, tzinfo=timezone.utc)
EVENT_ID = "550e8400-e29b-41d4-a716-446655440000"


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket = bucket
        self.name = name

    def upload_from_string(self, data, **kwargs):
        self.bucket.upload_arguments.append(kwargs)
        if kwargs.get("if_generation_match") != 0:
            raise AssertionError("receipt write must be create-only")
        if self.name in self.bucket.objects:
            raise PreconditionFailed("already exists")
        self.bucket.objects[self.name] = bytes(data)

    def reload(self, **_kwargs):
        if self.name not in self.bucket.objects:
            raise NotFound("missing")

    def download_as_bytes(self, **_kwargs):
        return self.bucket.objects[self.name]


class FakeBucket:
    def __init__(self):
        self.objects = {}
        self.upload_arguments = []

    def blob(self, name):
        return FakeBlob(self, name)


class FakeStorageClient:
    def __init__(self):
        self.fake_bucket = FakeBucket()

    def bucket(self, name):
        self.bucket_name = name
        return self.fake_bucket


class ReceiptStoreTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeStorageClient()
        self.store = CloudStorageReceiptStore("lab09-partner-a-receipts", client=self.client)

    def write(self, payload_hash="a" * 64, attempt=1):
        return self.store.create_or_compare(
            partner_id="partner-a",
            event_id=EVENT_ID,
            payload_sha256=payload_hash,
            received_at=NOW,
            attempt_number=attempt,
        )

    def test_create_uses_generation_zero_and_persists_only_receipt_metadata(self):
        result = self.write()
        self.assertEqual(result.outcome, "created")
        self.assertEqual(self.client.fake_bucket.upload_arguments[0]["if_generation_match"], 0)
        receipt = json.loads(self.client.fake_bucket.objects[result.object_name])
        self.assertEqual(receipt["payload_sha256"], "a" * 64)
        self.assertNotIn("order_ref", receipt)
        self.assertNotIn("signature", receipt)

    def test_existing_same_hash_is_duplicate_even_on_later_attempt(self):
        first = self.write(attempt=1)
        duplicate = self.write(attempt=3)
        self.assertEqual(first.outcome, "created")
        self.assertEqual(duplicate.outcome, "duplicate")

    def test_existing_different_hash_is_conflict_not_success(self):
        self.write(payload_hash="a" * 64)
        self.assertEqual(self.write(payload_hash="b" * 64).outcome, "conflict")

    def test_malformed_existing_receipt_fails_closed(self):
        self.client.fake_bucket.objects["events/partner-a/" + EVENT_ID + ".json"] = b"not-json"
        self.assertEqual(self.write().outcome, "conflict")


if __name__ == "__main__":
    unittest.main()
