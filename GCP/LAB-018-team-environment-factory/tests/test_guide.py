from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class Lab018GuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_tasks_are_ordered_and_have_expected_results_and_evidence(self):
        tasks = re.findall(r"^### Task (\d{2}) — .+$", self.readme, re.MULTILINE)
        self.assertEqual(tasks, [f"{i:02d}" for i in range(17)])
        sections = re.split(r"(?=^### Task \d{2} — )", self.readme, flags=re.MULTILINE)[1:]
        for section in sections:
            title = section.splitlines()[0]
            self.assertIn("**ผลที่คาดหวัง:**", section, title)
            self.assertIn("**บันทึกจริง / หลักฐาน:**", section, title)

    def test_brief_design_and_operations_precede_case_study(self):
        self.assertLess(self.readme.index("## Requirements"), self.readme.index("## Architecture decisions"))
        self.assertLess(self.readme.index("## Architecture decisions"), self.readme.index("### Task 00 —"))
        for section in ("## Troubleshooting", "## บันทึกผลเป็น Case Study", "## References"):
            self.assertIn(section, self.readme)

    def test_repository_links_point_to_files(self):
        targets = re.findall(r"!?(\[[^\]]*\])\(([^)]+)\)", self.readme)
        for _, target in targets:
            target = target.split("#", 1)[0]
            if not target or target.startswith(("https://", "http://", "mailto:")):
                continue
            self.assertTrue((ROOT / target).resolve().is_file(), target)

    def test_bash_examples_parse_without_running(self):
        fence = chr(96) * 3
        snippets = re.findall(
            r"(?m)^[ \t]{0,3}" + re.escape(fence) + r"bash\n([\s\S]*?)\n[ \t]{0,3}" + re.escape(fence) + r"[ \t]*$",
            self.readme,
        )
        self.assertGreaterEqual(len(snippets), 18)
        for index, snippet in enumerate(snippets):
            result = subprocess.run(
                ["bash", "-n"],
                input=snippet,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, f"bash example {index + 1}: {result.stderr}\n{snippet}")

    def test_cloud_status_and_dangerous_boundaries_are_explicit(self):
        self.assertIn("**Cloud verification:** Not run", self.readme)
        self.assertIn("alert-only", self.readme)
        self.assertIn("force-unlock", self.readme)
        self.assertIn("ไม่มีการสร้าง GCP resources", self.readme)
        self.assertIn("Project-wide IAM scope", self.readme)


if __name__ == "__main__":
    unittest.main()
