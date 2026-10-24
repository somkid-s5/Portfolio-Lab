from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

from lab13.contract import ContractError, parse_manifest_bytes, validate_shard_bytes
from generate_dataset import generate


class ContractTests(unittest.TestCase):
    def test_manifest_and_shards_validate_hash_count_and_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = generate("lab13-input-abc123", "lab13-contract-001", 2, 5, Path(tmp))
            raw_manifest = (Path(tmp) / "lab13-contract-001" / "manifest.json").read_bytes()
            parsed = parse_manifest_bytes(raw_manifest)
            self.assertEqual(parsed["total_records"], 10)
            shard_path = Path(tmp) / "lab13-contract-001" / "shards" / "shard-00000.jsonl"
            result = validate_shard_bytes(shard_path.read_bytes(), manifest["shards"][0])
            self.assertEqual(result["record_count"], 5)
            self.assertGreater(result["units_total"], 0)

    def test_rejects_changed_bytes_and_malformed_jsonl(self):
        raw = b'{"sku":"SKU-00000001","units":1,"unit_price_minor":100}\n'
        entry = {"index": 0, "record_count": 1, "sha256": hashlib.sha256(raw).hexdigest()}
        self.assertEqual(validate_shard_bytes(raw, entry)["record_count"], 1)
        with self.assertRaises(ContractError):
            validate_shard_bytes(raw + b" ", entry)
        malformed = b'{"sku":"SKU-00000001","units":\n'
        entry["sha256"] = hashlib.sha256(malformed).hexdigest()
        with self.assertRaises(ContractError):
            validate_shard_bytes(malformed, entry)

    def test_rejects_non_contiguous_or_duplicate_manifest_entries(self):
        manifest = generate_manifest_for_test()
        manifest["shards"][1]["index"] = 0
        with self.assertRaises(ContractError):
            parse_manifest_bytes(json.dumps(manifest).encode())

    def test_rejects_nul_in_object_uri(self):
        manifest = generate_manifest_for_test()
        manifest["shards"][0]["uri"] = manifest["shards"][0]["uri"].replace("shard-00000", "bad\x00path")
        with self.assertRaises(ContractError):
            parse_manifest_bytes(json.dumps(manifest).encode())

    def test_rejects_unordered_shard_array(self):
        manifest = generate_manifest_for_test()
        manifest["shards"].reverse()
        with self.assertRaises(ContractError):
            parse_manifest_bytes(json.dumps(manifest).encode())

    def test_rejects_wrong_run_id_and_bad_uri(self):
        manifest = generate_manifest_for_test()
        with self.assertRaises(ContractError):
            parse_manifest_bytes(json.dumps(manifest).encode(), "lab13-other-001")
        manifest["shards"][0]["uri"] = "https://example.invalid/input.jsonl"
        with self.assertRaises(ContractError):
            parse_manifest_bytes(json.dumps(manifest).encode())


def generate_manifest_for_test():
    raw = b'{"sku":"SKU-00000000","units":1,"unit_price_minor":100}\n'
    return {
        "schema_version": 1, "run_id": "lab13-contract-001",
        "shard_count": 2, "total_records": 2, "records_per_shard": 1,
        "shards": [
            {"index": index, "uri": f"gs://lab13-input-abc123/runs/lab13-contract-001/shards/shard-{index:05d}.jsonl",
             "record_count": 1, "sha256": hashlib.sha256(raw).hexdigest()}
            for index in range(2)
        ],
    }


if __name__ == "__main__":
    unittest.main()
