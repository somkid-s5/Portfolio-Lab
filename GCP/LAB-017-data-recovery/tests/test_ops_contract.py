import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DELETE_TOOL = (ROOT / "scripts" / "delete_fixture_object.py").read_text(encoding="utf-8")
CAPTURE_TOOL = (ROOT / "scripts" / "capture_manifest.py").read_text(encoding="utf-8")


class Lab017OperatorContracts(unittest.TestCase):
    def test_object_fault_is_exact_fixture_only_and_requires_execute(self):
        self.assertIn("DRILL_ID = \"LAB017-DRILL-01\"", DELETE_TOOL)
        self.assertIn("expected_prefix = f\"records/{DRILL_ID}/{record_ref}/\"", DELETE_TOOL)
        self.assertIn('parser.add_argument("--execute", action="store_true"', DELETE_TOOL)
        self.assertIn('"--if-generation-match={generation}"', DELETE_TOOL)
        self.assertNotIn("--recursive", DELETE_TOOL)
        ast.parse(DELETE_TOOL)

    def test_baseline_fails_closed_if_any_object_is_bad(self):
        self.assertIn('if not manifest.get("integrity_pass"):', CAPTURE_TOOL)
        self.assertIn("do not start the recovery drill", CAPTURE_TOOL)


if __name__ == "__main__":
    unittest.main()
