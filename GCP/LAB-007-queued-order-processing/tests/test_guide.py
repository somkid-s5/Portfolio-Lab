"""Repository checks for the executable Lab 07 guide."""
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

    def test_all_ordered_tasks_have_expected_and_actual_evidence_fields(self):
        headings = re.findall(r"^### Task (\d{2}) — .+$", self.readme, re.MULTILINE)
        self.assertEqual(headings, [f"{number:02d}" for number in range(13)])
        sections = re.split(r"^### Task \d{2} — .+$", self.readme, flags=re.MULTILINE)[1:]
        self.assertEqual(len(sections), 13)
        for number, section in enumerate(sections):
            with self.subTest(task=number):
                self.assertIn("**Expected:**", section)
                self.assertIn("**Actual / Evidence:**", section)

    def test_bash_fences_are_syntax_valid(self):
        blocks = re.findall(r"^~~~bash\n(.*?)^~~~$", self.readme, re.MULTILINE | re.DOTALL)
        self.assertGreaterEqual(len(blocks), 19)
        for number, block in enumerate(blocks):
            result = subprocess.run(["bash", "-n"], input=block, text=True,
                                    capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, f"bash block {number}: {result.stderr}")

    def test_cloud_build_is_not_confused_with_cloud_verification(self):
        self.assertIn("guide_status: authoring", self.readme)
        self.assertIn("cloud_verification: not-run", self.readme)
        self.assertIn("Cloud verification", self.readme)
        self.assertIn("Cloud Build source bucket", self.readme)


if __name__ == "__main__":
    unittest.main()
