from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class Lab020BriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_title_status_and_cloud_boundary(self):
        self.assertIn("# Lab 20 — แพลตฟอร์มจองและสร้างรายงานแบบรับมอบงานได้", self.readme)
        self.assertTrue("Guide review pending" in self.readme or "Guide-ready" in self.readme)
        self.assertIn("Cloud verification:** Not run", self.readme)
        self.assertIn("GitHub CI ตรวจ source/contract เท่านั้น ไม่สร้าง GCP resources", self.readme)
        self.assertIn("ไม่ถือ Expected เป็น PASS", self.readme)

    def test_requirements_are_numbered_and_acceptance_is_measurable(self):
        ids = re.findall(r"^\| (R\d{2}) \|", self.readme, re.MULTILINE)
        self.assertEqual(ids, [f"R{i:02d}" for i in range(1, 17)])
        for phrase in ("IAP", "Pub/Sub", "Cloud Run", "Cloud SQL", "DLQ",
                       "booking_source", "rollback", "single-zone", "actor_hash"):
            self.assertIn(phrase, self.readme)

    def test_design_change_request_and_collection_alignment(self):
        for phrase in ("## Architecture และการตัดสินใจ", "## Change Request",
                       "## คู่มือทำ Solution Lab", "## Portfolio case-study summary",
                       "อ้างอิง visual style จาก ZIP", "ชุดไอคอนบริการ Google Cloud"):
            self.assertIn(phrase, self.readme)
        self.assertIn("การมี style reference ไม่เท่ากับยืนยันว่าได้เรียกใช้ Personal Custom Skill", self.readme)
        self.assertIn("CR-20-01", self.readme)
        self.assertIn("migration_image_digest", self.readme)
        self.assertIn("same digest", self.readme)


if __name__ == "__main__":
    unittest.main()
