from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

from generate_dataset import generate
from lab13.worker import EXIT_PERMANENT, EXIT_TRANSIENT, run_task


class FakeBlob:
    def __init__(self, name, bucket, objects):
        self.name, self.bucket, self.objects = name, bucket, objects

    def download_as_bytes(self):
        return self.objects[(self.bucket, self.name)]

    def upload_from_string(self, raw, **kwargs):
        key = (self.bucket, self.name)
        if kwargs.get("if_generation_match") == 0 and key in self.objects:
            raise RuntimeError("precondition failed")
        self.objects[key] = raw


class FakeBucket:
    def __init__(self, name, objects):
        self.name, self.objects = name, objects

    def blob(self, name):
        return FakeBlob(name, self.name, self.objects)


class FakeClient:
    def __init__(self, objects):
        self.objects = objects

    def bucket(self, name):
        return FakeBucket(name, self.objects)


class WorkerTests(unittest.TestCase):
    def dataset(self, malformed=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manifest = generate("lab13-input-abc123", "lab13-worker-test", 2, 3,
                            Path(tmp.name), malformed)
        run = manifest["run_id"]
        root = Path(tmp.name) / run
        objects = {("lab13-input-abc123", f"runs/{run}/manifest.json"):
                   (root / "manifest.json").read_bytes()}
        for shard in manifest["shards"]:
            obj = shard["uri"].split("/", 3)[3]
            objects[("lab13-input-abc123", obj)] = (root / "shards" / Path(obj).name).read_bytes()
        return manifest, objects

    def environment(self, run, **extra):
        env = {
            "INPUT_MANIFEST_URI": f"gs://lab13-input-abc123/runs/{run}/manifest.json",
            "ATTEMPT_OUTPUT_BUCKET": "lab13-attempt-abc123",
            "BATCH_TASK_INDEX": "0",
            "BATCH_TASK_COUNT": "2",
            "BATCH_TASK_RETRY_ATTEMPT": "0",
        }
        env.update(extra)
        return env

    def test_retryable_injection_writes_only_on_second_attempt_path(self):
        manifest, objects = self.dataset()
        client = FakeClient(objects)
        env = self.environment(manifest["run_id"], LAB13_FAIL_ONCE_INDEX="0")
        self.assertEqual(run_task(env, client), EXIT_TRANSIENT)
        self.assertNotIn(("lab13-attempt-abc123",
                          f"runs/{manifest['run_id']}/shards/00000/attempt-0/result.json"), objects)
        env["BATCH_TASK_RETRY_ATTEMPT"] = "1"
        self.assertEqual(run_task(env, client), 0)
        result_key = ("lab13-attempt-abc123",
                      f"runs/{manifest['run_id']}/shards/00000/attempt-1/result.json")
        result = json.loads(objects[result_key])
        self.assertEqual(result["attempt"], 1)
        self.assertEqual(result["record_count"], 3)

    def test_malformed_data_returns_non_retryable_code_without_output(self):
        manifest, objects = self.dataset(malformed=0)
        client = FakeClient(objects)
        self.assertEqual(run_task(self.environment(manifest["run_id"]), client), EXIT_PERMANENT)
        self.assertFalse(any(bucket == "lab13-attempt-abc123" for bucket, _ in objects))


if __name__ == "__main__":
    unittest.main()
