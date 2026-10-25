"""Cloud Storage adapter contracts using SDK-shaped doubles; no RPCs or credentials."""
import hashlib
from pathlib import Path
import sys
import unittest

from google.api_core.exceptions import NotFound, PreconditionFailed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.storage import (ArtifactConflict, GCSObjects, InvalidSource, SourceMissing,
                         SourceChanged)


DAY = "2026-10-23"
SOURCE = f"incoming/business_date={DAY}/transactions.csv"


class FakeBlob:
    def __init__(self, bucket, name, generation=None):
        self.bucket, self.name, self.requested_generation = bucket, name, generation
        self.data = None
        self.generation = None
        self.size = None
        self.content_type = None
        self.content_encoding = None
        self.metadata = None
        self.cache_control = None
        self.content_disposition = None
        self.calls = []
        if name in bucket.objects:
            item = bucket.objects[name]
            self.data, self.generation = item["data"], item["generation"]
            self.size, self.content_type = len(self.data), item["content_type"]
            self.content_encoding = item.get("content_encoding")
            self.metadata = item.get("metadata")

    def reload(self, **kwargs):
        self.calls.append(("reload", kwargs))
        if self.name not in self.bucket.objects:
            raise NotFound("missing")
        item = self.bucket.objects[self.name]
        if self.requested_generation is not None and str(item["generation"]) != str(self.requested_generation):
            raise PreconditionFailed("generation changed")
        if kwargs.get("if_generation_match") is not None and str(item["generation"]) != str(kwargs["if_generation_match"]):
            raise PreconditionFailed("generation changed")
        self.data, self.generation = item["data"], item["generation"]
        self.size, self.content_type = len(self.data), item["content_type"]
        self.content_encoding = item.get("content_encoding")
        self.metadata = item.get("metadata")

    def download_to_file(self, buffer, **kwargs):
        self.calls.append(("download", kwargs))
        if self.name not in self.bucket.objects:
            raise NotFound("missing")
        item = self.bucket.objects[self.name]
        expected = kwargs.get("if_generation_match")
        if expected is not None and str(item["generation"]) != str(expected):
            raise PreconditionFailed("generation changed")
        buffer.write(item["data"])

    def upload_from_string(self, body, *, content_type, if_generation_match, **kwargs):
        self.calls.append(("upload", {"if_generation_match": if_generation_match, **kwargs}))
        if if_generation_match == 0 and self.name in self.bucket.objects:
            raise PreconditionFailed("already exists")
        generation = self.bucket.next_generation
        self.bucket.next_generation += 1
        self.bucket.objects[self.name] = {
            "data": body, "generation": generation, "content_type": content_type,
            "metadata": self.metadata,
        }
        self.data, self.generation = body, generation
        self.size, self.content_type = len(body), content_type


class FakeBucket:
    def __init__(self, name):
        self.name, self.objects, self.next_generation = name, {}, 100

    def blob(self, name, generation=None):
        return FakeBlob(self, name, generation)


class FakeStorage:
    def __init__(self):
        self.buckets = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, FakeBucket(name))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeStorage()
        self.objects = GCSObjects(self.client, "source-bucket", "report-bucket")
        self.source = self.client.buckets["source-bucket"]

    def test_default_source_path_and_generation_pinned_read(self):
        self.source.objects[SOURCE] = {"data": b"transaction,csv", "generation": 123,
                                      "content_type": "text/csv"}
        generation = self.objects.source_generation(SOURCE, business_date=DAY)
        self.assertEqual(generation, "123")
        self.assertEqual(self.objects.read_source(SOURCE, generation,
                                                   business_date=DAY), b"transaction,csv")

    def test_missing_or_wrong_date_source_is_not_followed(self):
        with self.assertRaises(SourceMissing):
            self.objects.source_generation(SOURCE, business_date=DAY)
        with self.assertRaisesRegex(ValueError, "invalid_object_name"):
            self.objects.source_generation(
                "incoming/business_date=2026-10-22/transactions.csv", business_date=DAY)

    def test_source_generation_mismatch_and_oversize_fail_closed(self):
        self.source.objects[SOURCE] = {"data": b"abc", "generation": 123,
                                      "content_type": "text/csv"}
        with self.assertRaises(SourceChanged):
            self.objects.read_source(SOURCE, "122", business_date=DAY)
        self.source.objects[SOURCE]["data"] = b"x" * (5 * 1024 * 1024 + 1)
        generation = self.objects.source_generation(SOURCE, business_date=DAY)
        with self.assertRaisesRegex(InvalidSource, "INPUT_TOO_LARGE"):
            self.objects.read_source(SOURCE, generation, business_date=DAY)

    def test_wrong_content_type_is_classified_after_generation_is_claimable(self):
        self.source.objects[SOURCE] = {
            "data": b"not csv", "generation": 123, "content_type": "application/octet-stream"
        }
        generation = self.objects.source_generation(SOURCE, business_date=DAY)
        with self.assertRaisesRegex(InvalidSource, "INVALID_CONTENT_TYPE"):
            self.objects.read_source(SOURCE, generation, business_date=DAY)

    def test_create_only_report_is_reused_only_when_body_and_metadata_match(self):
        body = b'{"report_id":"r"}\n'
        digest = hashlib.sha256(body).hexdigest()
        args = {"source_generation": "123", "source_sha256": "a"*64,
                "report_id": "b"*64}
        first = self.objects.create_report(DAY, body, **args)
        second = self.objects.create_report(DAY, body, **args)
        self.assertEqual(first, second)
        with self.assertRaisesRegex(ArtifactConflict, "existing_report_mismatch"):
            self.objects.create_report(DAY, b'{"other":true}\n', **args)
        self.assertEqual(self.objects.verify_report(first["object"], first["generation"],
            expected_sha256=digest,
            expected_metadata={"report_id": "b"*64}), body)

    def test_watchdog_detects_hash_and_metadata_tampering(self):
        body = b'{"report":1}\n'
        digest = hashlib.sha256(body).hexdigest()
        meta = {"source_generation": "123", "source_sha256": "a"*64,
                "report_id": "b"*64}
        report = self.objects.create_report(DAY, body, **meta)
        with self.assertRaisesRegex(ArtifactConflict, "report_binding_mismatch"):
            self.objects.verify_report(report["object"], report["generation"],
                expected_sha256=digest, expected_metadata={"report_id": "c"*64})
        blob = self.client.buckets["report-bucket"].objects[report["object"]]
        blob["data"] = b'{"tampered":true}'
        with self.assertRaises(ArtifactConflict):
            self.objects.verify_report(report["object"], report["generation"],
                expected_sha256=digest)

    def test_rejects_shared_buckets_and_bad_generation(self):
        with self.assertRaisesRegex(ValueError, "separate_buckets_required"):
            GCSObjects(self.client, "same", "same")
        with self.assertRaisesRegex(ValueError, "invalid_generation"):
            self.objects.read_source(SOURCE, "latest", business_date=DAY)


if __name__ == "__main__":
    unittest.main()
