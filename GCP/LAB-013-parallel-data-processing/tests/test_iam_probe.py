from __future__ import annotations

import sys
import unittest
from pathlib import Path

from google.api_core.exceptions import Forbidden

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from lab13.iam_probe import run


class DeniedBlob:
    def __init__(self, bucket, name, calls):
        self.bucket, self.name, self.calls = bucket, name, calls

    def upload_from_string(self, raw, **kwargs):
        self.calls.append((self.bucket, self.name, kwargs.get("if_generation_match")))
        raise Forbidden("storage.objects.create denied")


class Bucket:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    def blob(self, name):
        return DeniedBlob(self.name, name, self.calls)


class DeniedClient:
    def __init__(self):
        self.calls = []

    def bucket(self, name):
        return Bucket(name, self.calls)


class IAMProbeTests(unittest.TestCase):
    def test_runtime_probe_requires_denial_in_both_protected_buckets(self):
        client = DeniedClient()
        self.assertEqual(run("lab13-input-abc123", "lab13-published-abc123",
                             "lab13-probe-001", client), 0)
        self.assertEqual([item[0] for item in client.calls],
                         ["lab13-input-abc123", "lab13-published-abc123"])
        self.assertTrue(all(item[2] == 0 for item in client.calls))


if __name__ == "__main__":
    unittest.main()
