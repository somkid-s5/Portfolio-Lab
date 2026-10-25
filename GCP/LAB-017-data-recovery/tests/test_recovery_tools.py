import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from compare_manifest import compare_manifests
from measure_recovery import build_report

BASE = {
    "drill_id": "LAB017-DRILL-01",
    "objects_ok": True,
    "integrity_pass": True,
    "database": {
        "count": 1, "total_amount_cents": 500, "max_id": 7,
        "sequence_last_value": 7, "sequence_is_called": True,
        "by_status": {"NEW": 1},
        "records": [{
            "id": 7, "record_ref": "LAB017-REC-001", "title": "Fixture", "status": "NEW",
            "amount_cents": 500, "state": "READY", "attachment_key": "records/LAB017-DRILL-01/a.txt",
            "attachment_sha256": "a" * 64, "attachment_bytes": 4, "attachment_generation": 100,
        }],
    },
}


class RecoveryToolsTests(unittest.TestCase):
    def test_manifest_pass_ignores_new_storage_generation_only(self):
        current = {**BASE, "database": {**BASE["database"], "records": [
            {**BASE["database"]["records"][0], "attachment_generation": 200}
        ]}}
        self.assertEqual(compare_manifests(BASE, current), [])

    def test_manifest_detects_missing_record_checksum_and_sequence_drift(self):
        current = {**BASE, "integrity_pass": False, "objects_ok": False, "database": {
            **BASE["database"], "count": 0, "sequence_last_value": 6, "records": [],
        }}
        errors = compare_manifests(BASE, current)
        self.assertTrue(any("integrity_pass" in item for item in errors))
        self.assertTrue(any("record_ref set differs" in item for item in errors))
        self.assertTrue(any("sequence_last_value differs" in item for item in errors))
        self.assertTrue(any("attachments" in item for item in errors))

    def test_recovery_measurement_uses_actual_utc_intervals(self):
        report = build_report(
            "2026-10-25T10:00:00Z",
            "2026-10-25T09:57:30Z",
            "2026-10-25T10:18:00Z",
        )
        self.assertEqual(report["observed_rpo_seconds"], 150)
        self.assertEqual(report["observed_rto_seconds"], 1080)
        self.assertTrue(report["rpo_target_met"])
        self.assertTrue(report["rto_target_met"])

    def test_invalid_recovery_timeline_is_rejected(self):
        with self.assertRaises(ValueError):
            build_report("2026-10-25T10:00:00Z", "2026-10-25T10:01:00Z", "2026-10-25T10:02:00Z")
        with self.assertRaises(ValueError):
            build_report("2026-10-25T10:00:00Z", "2026-10-25T09:59:00Z", "2026-10-25T09:58:00Z")


if __name__ == "__main__":
    unittest.main()
