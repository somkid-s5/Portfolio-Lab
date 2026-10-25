from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class Lab017GuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_tasks_are_ordered_and_have_expected_results_and_evidence(self):
        tasks = re.findall(r"^### Task (\d{2}) — .+$", self.readme, re.MULTILINE)
        self.assertEqual(tasks, [f"{i:02d}" for i in range(20)])
        sections = re.split(r"(?=^### Task \d{2} — )", self.readme, flags=re.MULTILINE)[1:]
        self.assertEqual(len(sections), 20)
        for section in sections:
            task = section.splitlines()[0]
            self.assertIn("**ผลที่คาดหวัง:**", section, task)
            self.assertIn("**บันทึกจริง / หลักฐาน:**", section, task)

    def test_requirements_design_precede_tasks(self):
        self.assertLess(self.readme.index("## Requirements และเกณฑ์รับงาน"), self.readme.index("## Architecture decisions"))
        self.assertLess(self.readme.index("## Architecture decisions"), self.readme.index("### Task 00 —"))
        for heading in ("## Troubleshooting", "## บันทึกผลเป็น Case Study", "## References"):
            self.assertIn(heading, self.readme)

    def test_local_links_and_images_exist(self):
        targets = re.findall(r"!?(?:\[[^\]]*\])\(([^)]+)\)", self.readme)
        for target in targets:
            target = target.split("#", 1)[0]
            if not target or target.startswith(("https://", "http://", "mailto:")):
                continue
            self.assertTrue((ROOT / target).resolve().is_file(), target)

    def test_bash_examples_parse_without_executing(self):
        fence = chr(96) * 3
        snippets = re.findall(r"(?m)^[ \t]{0,3}" + re.escape(fence) + r"bash\n([\s\S]*?)\n[ \t]{0,3}" + re.escape(fence) + r"[ \t]*$", self.readme)
        self.assertGreaterEqual(len(snippets), 15)
        for index, snippet in enumerate(snippets):
            result = subprocess.run(
                ["bash", "-n"],
                input=snippet,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, f"bash snippet {index + 1}: {result.stderr}\n{snippet}")

    def test_cloud_verification_boundary_and_recovery_contract(self):
        self.assertIn("**Cloud verification:** Not run", self.readme)
        self.assertIn("ไม่ใช่คำรับรองของ Google Cloud", self.readme)
        self.assertIn("ห้าม dual-writer", self.readme)
        self.assertIn("PITR สร้าง instance ใหม่", self.readme)
        self.assertIn("recovery_gate=PASS", self.readme)
        self.assertIn("ยังไม่ได้ทดสอบบน GCP", self.readme)
        self.assertIn("GET DIAGNOSTICS updated_rows = ROW_COUNT", self.readme)
        self.assertIn("RAISE EXCEPTION", self.readme)


if __name__ == "__main__":
    unittest.main()
