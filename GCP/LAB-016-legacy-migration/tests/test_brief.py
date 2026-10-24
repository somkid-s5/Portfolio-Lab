from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]
LAB_README = ROOT / "GCP" / "LAB-016-legacy-migration" / "README.md"
ROADMAP = ROOT / "GCP" / "ROADMAP.md"


class Lab016BriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = LAB_README.read_text(encoding="utf-8")
        cls.roadmap = ROADMAP.read_text(encoding="utf-8")

    def test_requirements_are_complete_and_identifiable(self):
        ids = re.findall(r"^\| (R\d{2}) \|", self.readme, re.MULTILINE)
        self.assertEqual(ids, [f"R{i:02d}" for i in range(1, 11)])
        for required in ("## สถานการณ์", "## ข้อกำหนดและวิธีพิสูจน์", "## บันทึกผลและหลักฐานระหว่างทำ", "## Case-study summary"):
            self.assertIn(required, self.readme)

    def test_verification_is_not_fabricated(self):
        self.assertIn("Cloud verification:** Not run", self.readme)
        self.assertIn("ยังไม่มีการสร้างหรือทดสอบทรัพยากร GCP", self.readme)
        self.assertNotRegex(self.readme.lower(), r"cloud[- ]verified\s*[:=]\s*pass")

    def test_official_references_and_scope_are_recorded(self):
        self.assertIn("docs.cloud.google.com/database-migration/docs/postgres/scenario-overview", self.readme)
        self.assertIn("docs.cloud.google.com/load-balancing/docs/https/use-cases", self.readme)
        self.assertIn("Cloud Run", self.readme)
        self.assertIn("Cloud SQL", self.readme)
        self.assertIn("write-freeze", self.readme)

    def test_roadmap_lab_15_and_16_sections_are_repaired_and_unique(self):
        self.assertEqual(self.roadmap.count('<a id="lab-15"></a>'), 1)
        self.assertEqual(self.roadmap.count('<a id="lab-16"></a>'), 1)
        self.assertIn("### 15 — ระบบสำนักงานสาขาเชื่อมบริการ Private บน Cloud", self.roadmap)
        self.assertIn("### 16 — ย้ายระบบ Legacy พร้อมข้อมูลขึ้น Cloud", self.roadmap)
        self.assertNotIn("จำลอ<a id=", self.roadmap)
        self.assertNotIn("pp/PostgreSQL", self.roadmap)


if __name__ == "__main__":
    unittest.main()
