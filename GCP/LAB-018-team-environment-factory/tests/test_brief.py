from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class Lab018BriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_roadmap_title_matches(self):
        self.assertIn("# Lab 18 — แพลตฟอร์มสร้าง Environment ให้ทีมใหม่", self.readme)

    def test_requirements_are_numbered_and_complete(self):
        ids = re.findall(r"^\| (R\d{2}) \|", self.readme, re.MULTILINE)
        self.assertEqual(ids, [f"R{i:02d}" for i in range(1, 13)])

    def test_brief_and_design_precede_task_authoring(self):
        for section in ("## Requirements", "## Acceptance Criteria", "## Architecture decisions",
                        "## Change Request", "## References"):
            self.assertIn(section, self.readme)
        self.assertNotRegex(self.readme, r"(?m)^## Task \d{2}")

    def test_project_creator_owner_handoff_is_explicit(self):
        self.assertIn("roles/resourcemanager.projectCreator", self.readme)
        self.assertIn("Google Cloud สร้าง roles/owner ให้ principal ที่สร้าง Project โดยอัตโนมัติ", self.readme)
        self.assertIn("ถอน Owner", self.readme)
        self.assertIn("ไม่มี roles/owner หรือ roles/editor", self.readme)

    def test_budget_alert_and_cloud_boundary_are_explicit(self):
        self.assertIn("alert-only", self.readme)
        self.assertIn("ไม่ได้จำกัดค่าใช้จ่ายโดยอัตโนมัติ", self.readme)
        self.assertIn("ไม่แก้ Organization Policy", self.readme)
        self.assertIn("Cloud verification:** Not run", self.readme)

    def test_required_design_constraints_and_sources_exist(self):
        for phrase in ("asia-southeast1", "asia-east1", "GCS backend", "state locking",
                       "roles/logging.logWriter", "roles/logging.bucketWriter", "bucket ไม่มี IAM policy ราย bucket", "Project ID", "project ส่วนตัว"):
            self.assertIn(phrase, self.readme)
        for url in (
            "https://docs.cloud.google.com/resource-manager/docs/access-control-proj",
            "https://developer.hashicorp.com/terraform/language/backend/gcs",
            "https://docs.cloud.google.com/logging/docs/export/configure_export_v2",
        ):
            self.assertIn(url, self.readme)


if __name__ == "__main__":
    unittest.main()
