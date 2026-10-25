import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.api_core.exceptions import NotFound
from scripts.restore_object_generation import MAX_BYTES, restore_generation



class FakeBlob:
    def __init__(self, bucket, name, generation=None):
        self.bucket = bucket
        self.name = name
        self.generation = generation
        self.content_type = "text/csv"
        self.size = None

    def reload(self):
        if self.generation is None:
            if self.name not in self.bucket.current:
                raise self.bucket.not_found()
            obj = self.bucket.current[self.name]
        else:
            obj = self.bucket.versions.get((self.name, int(self.generation)))
            if obj is None:
                raise self.bucket.not_found()
        self.size = len(obj["data"])
        self.content_type = obj["content_type"]
        if self.generation is None:
            self.generation = obj["generation"]

    def download_as_bytes(self):
        key = (self.name, int(self.generation))
        return self.bucket.versions[key]["data"]

    def upload_from_string(self, data, content_type, if_generation_match):
        current = self.bucket.current.get(self.name)
        actual = int(current["generation"]) if current else 0
        if actual != if_generation_match:
            raise RuntimeError("generation precondition failed")
        generation = actual + 1
        value = {"generation": generation, "data": data, "content_type": content_type}
        self.bucket.current[self.name] = value
        self.bucket.versions[(self.name, generation)] = value
        self.generation = generation

    def bucket_object(self):
        return self.bucket


class FakeBucket:
    def __init__(self):
        self.current = {}
        self.versions = {}

    def not_found(self):
        return NotFound()

    def blob(self, name, generation=None):
        return FakeBlob(self, name, generation)


class FakeClient:
    def __init__(self, bucket):
        self._bucket = bucket

    def bucket(self, name):
        return self._bucket


class RestoreToolTests(unittest.TestCase):
    def setUp(self):
        self.bucket = FakeBucket()
        first = {"generation": 1, "data": b"old", "content_type": "text/csv"}
        second = {"generation": 2, "data": b"new", "content_type": "text/csv"}
        self.bucket.versions[("stage/reports/a.csv", 1)] = first
        self.bucket.versions[("stage/reports/a.csv", 2)] = second
        self.bucket.current["stage/reports/a.csv"] = second
        self.client = FakeClient(self.bucket)

    def test_dry_run_does_not_change_current_generation(self):
        self.assertIsNone(
            restore_generation(self.client, "bucket", "stage/reports/a.csv", 1, apply=False)
        )
        self.assertEqual(self.bucket.current["stage/reports/a.csv"]["data"], b"new")

    def test_apply_writes_old_bytes_as_a_new_generation(self):
        generation = restore_generation(
            self.client, "bucket", "stage/reports/a.csv", 1, apply=True
        )
        self.assertEqual(generation, 3)
        self.assertEqual(self.bucket.current["stage/reports/a.csv"]["data"], b"old")
        self.assertEqual(self.bucket.versions[("stage/reports/a.csv", 2)]["data"], b"new")

    def test_oversized_object_is_rejected_before_download(self):
        self.bucket.versions[("stage/reports/a.csv", 1)] = {
            "generation": 1,
            "data": b"x" * (MAX_BYTES + 1),
            "content_type": "text/csv",
        }
        with self.assertRaises(ValueError):
            restore_generation(self.client, "bucket", "stage/reports/a.csv", 1, apply=False)


if __name__ == "__main__":
    unittest.main()
