"""Repository checks for the executable Lab 08 guide."""
from pathlib import Path
import re
import subprocess
import unittest

LAB = Path(__file__).resolve().parents[1]
README = LAB / "README.md"


class GuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_ordered_tasks_have_expected_and_actual_evidence_fields(self):
        headings = re.findall(r"^### Task (\d{2}) — .+$", self.readme, re.MULTILINE)
        self.assertEqual(headings, [f"{number:02d}" for number in range(13)])
        sections = re.split(r"^### Task \d{2} — .+$", self.readme, flags=re.MULTILINE)[1:]
        self.assertEqual(len(sections), 13)
        for number, section in enumerate(sections):
            with self.subTest(task=number):
                self.assertIn("**Expected:**", section)
                self.assertIn("**Actual / Evidence:**", section)

    def test_bash_fences_parse_without_executing(self):
        blocks = re.findall(r"^~~~bash\n(.*?)^~~~$", self.readme, re.MULTILINE | re.DOTALL)
        self.assertGreaterEqual(len(blocks), 18)
        for number, block in enumerate(blocks):
            result = subprocess.run(["bash", "-n"], input=block, text=True,
                                    capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, f"bash block {number}: {result.stderr}")

    def test_relative_markdown_links_exist(self):
        links = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", self.readme)
        for target in links:
            target = target.split("#", 1)[0]
            if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            with self.subTest(link=target):
                self.assertTrue((LAB / target).resolve().is_file(), target)

    def test_cloud_verification_is_not_claimed(self):
        self.assertIn("guide_status: authoring", self.readme)
        self.assertIn("cloud_verification: not-run", self.readme)
        self.assertNotIn("reportctl status", self.readme)
        self.assertNotIn("concurrency 2", self.readme)


if __name__ == "__main__":
    unittest.main()
