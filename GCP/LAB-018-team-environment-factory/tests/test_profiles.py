from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_profiles import validate_candidate, validate_profile  # noqa: E402


class ProfileValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads((ROOT / "config" / "environments.json").read_text(encoding="utf-8"))
        cls.candidate = json.loads(
            (ROOT / "config" / "change-request-dataops.example.json").read_text(encoding="utf-8")
        )

    def test_baseline_profiles_are_structurally_valid(self):
        self.assertEqual(validate_profile(self.profile), [])

    def test_unapproved_region_is_rejected(self):
        errors = validate_candidate(self.profile, self.candidate)
        self.assertTrue(any("not in allowed_regions" in error for error in errors))

    def test_pending_approval_is_rejected(self):
        candidate = dict(self.candidate, region="asia-southeast1")
        errors = validate_candidate(self.profile, candidate)
        self.assertTrue(any("approval_reference" in error for error in errors))

    def test_duplicate_project_ids_are_rejected(self):
        profile = json.loads(json.dumps(self.profile))
        profile["environments"]["staging"]["project_id"] = profile["environments"]["dev"]["project_id"]
        self.assertTrue(any("duplicated" in error for error in validate_profile(profile)))


if __name__ == "__main__":
    unittest.main()
