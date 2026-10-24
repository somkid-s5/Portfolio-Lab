from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from google.api_core.exceptions import PreconditionFailed

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

from generate_dataset import generate
from lab13.contract import ContractError
from upload_dataset import upload_dataset


class FakeBlob:
    def __init__(self, bucket, name, objects, events):
        self.bucket, self.name, self.objects, self.events = bucket, name, objects, events

    def exists(self):
        return (self.bucket, self.name) in self.objects

    def download_as_bytes(self):
        return self.objects[(self.bucket, self.name)]

    def upload_from_filename(self, filename, **kwargs):
        key = (self.bucket, self.name)
        self.events.append(("upload", self.name))
        if kwargs.get("if_generation_match") != 0:
            raise AssertionError("all uploads must use create-only generation preconditions")
        if key in self.objects:
            raise PreconditionFailed("object already exists")
        self.objects[key] = Path(filename).read_bytes()


class FakeBucket:
    def __init__(self, name, objects, events):
        self.name, self.objects, self.events = name, objects, events

    def blob(self, name):
        return FakeBlob(self.name, name, self.objects, self.events)


class FakeClient:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.events = []
        self.bucket_names = []

    def bucket(self, name):
        self.bucket_names.append(name)
        return FakeBucket(name, self.objects, self.events)


class UploadTests(unittest.TestCase):
    def make_dataset(self, root, run_id, shards=2, records=3, malformed=None):
        manifest = generate("lab13-input-abc123", run_id, shards, records, root, malformed)
        return root / run_id, manifest

    def test_uploads_every_shard_before_create_only_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, manifest = self.make_dataset(Path(tmp), "lab13-upload-001")
            client = FakeClient()
            result = upload_dataset(run_dir, "lab13-input-abc123", client)
            self.assertEqual(len(result["uploaded_shards"]), 2)
            self.assertEqual(client.events[-1], ("upload", f"runs/{manifest['run_id']}/manifest.json"))
            self.assertEqual(sum(1 for kind, _ in client.events if kind == "upload"), 3)
            self.assertTrue(all(name.endswith(".jsonl") for kind, name in client.events[:-1]))

    def test_repeat_upload_verifies_objects_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, _ = self.make_dataset(Path(tmp), "lab13-upload-002")
            client = FakeClient()
            first = upload_dataset(run_dir, "lab13-input-abc123", client)
            upload_count = len(client.events)
            second = upload_dataset(run_dir, "lab13-input-abc123", client)
            self.assertEqual(len(client.events), upload_count)
            self.assertEqual(first["run_id"], second["run_id"])
            self.assertTrue(all("already-present-and-verified" in item for item in second["uploaded_shards"]))
            self.assertEqual(second["manifest_status"], "already-present-and-verified")

    def test_conflicting_existing_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, manifest = self.make_dataset(Path(tmp), "lab13-upload-003", shards=1)
            object_name = manifest["shards"][0]["uri"].split("/", 3)[3]
            client = FakeClient({("lab13-input-abc123", object_name): b"some other input\n"})
            with self.assertRaises(ContractError):
                upload_dataset(run_dir, "lab13-input-abc123", client)
            self.assertEqual(client.events, [])

    def test_conflicting_existing_manifest_fails_before_any_shard_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, manifest = self.make_dataset(Path(tmp), "lab13-upload-004", shards=1)
            manifest_object = f"runs/{manifest['run_id']}/manifest.json"
            client = FakeClient({("lab13-input-abc123", manifest_object): b'{"different":"manifest"}'})
            with self.assertRaises(ContractError):
                upload_dataset(run_dir, "lab13-input-abc123", client)
            self.assertEqual(client.events, [])

    def test_invalid_dataset_is_not_uploaded_unless_explicit_negative_test_is_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, manifest = self.make_dataset(Path(tmp), "lab13-bad-input-001", shards=1, malformed=0)
            client = FakeClient()
            with self.assertRaises(ContractError):
                upload_dataset(run_dir, "lab13-input-abc123", client)
            self.assertEqual(client.bucket_names, [])
            result = upload_dataset(run_dir, "lab13-input-abc123", client, allow_invalid_shard_index=0)
            self.assertEqual(result["manifest_status"], "uploaded")
            self.assertEqual(len(client.events), 2)
            self.assertEqual(client.events[-1], ("upload", f"runs/{manifest['run_id']}/manifest.json"))


if __name__ == "__main__":
    unittest.main()
