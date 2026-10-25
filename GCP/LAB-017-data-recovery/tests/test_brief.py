from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PROVENANCE = ROOT / "assets" / "diagram-provenance.json"


class Lab017BriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")
        cls.provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))

    def test_requirements_are_complete_and_numbered(self):
        ids = re.findall(r"^\| (R\d{2}) \|", self.readme, re.MULTILINE)
        self.assertEqual(ids, [f"R{i:02d}" for i in range(1, 11)])

    def test_brief_precedes_task_authoring(self):
        self.assertIn("## Architecture decisions", self.readme)
        self.assertIn("## Change Request", self.readme)
        self.assertIn("## References", self.readme)
        self.assertNotRegex(self.readme, r"(?m)^## Task \d{2}")

    def test_recovery_boundaries_are_explicit(self):
        for phrase in (
            "PITR สร้าง instance ใหม่",
            "soft delete 7 วัน",
            "ไม่ใช่คำรับรองของ Google Cloud",
            "ห้าม dual-writer",
            "RPO ≤ 5 นาที",
            "RTO ≤ 30 นาที",
        ):
            self.assertIn(phrase, self.readme)

    def test_diagram_style_is_a_reference_not_unverified_skill_claim(self):
        self.assertIn("อ้างอิงมาตรฐานสี ไอคอน", self.readme)
        self.assertIn("ยังไม่มีหลักฐานว่าได้เรียกใช้ Personal Custom Skill", self.readme)
        self.assertIn("docs/diagram-style.md", self.readme)
        self.assertEqual(self.provenance["style"], "Diagram Design — Personal Custom from the user's diagram-design.zip")
        self.assertEqual(self.provenance["cloud_verification"], "not-run")


if __name__ == "__main__":
    unittest.main()
