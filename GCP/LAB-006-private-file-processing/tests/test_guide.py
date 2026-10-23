"""Documentation syntax and link checks only, never execute cloud commands."""
from pathlib import Path
import re
import subprocess
import unittest
from urllib.parse import unquote, urlsplit

LAB = Path(__file__).resolve().parents[1]


class GuideTests(unittest.TestCase):
    def test_bash_examples_parse_without_execution(self):
        text = (LAB/"README.md").read_text()
        blocks = re.findall(r"^```bash\n(.*?)^```\s*$", text, re.M | re.S)
        self.assertGreaterEqual(len(blocks), 8)
        for number, block in enumerate(blocks, 1):
            with self.subTest(block=number):
                result = subprocess.run(["bash", "--noprofile", "--norc", "-n"],
                                        input=block, text=True, capture_output=True,
                                        timeout=10, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_relative_links_have_committed_targets(self):
        text = (LAB/"README.md").read_text()
        checked = 0
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith("#"):
                continue
            with self.subTest(target=target):
                path = (LAB/unquote(parsed.path)).resolve()
                self.assertTrue(path.is_relative_to(LAB.parents[1]))
                self.assertTrue(path.is_file(), target)
            checked += 1
        self.assertGreaterEqual(checked, 10)

    def test_authored_tasks_keep_cloud_evidence_unclaimed(self):
        text = (LAB/"README.md").read_text()
        for number in range(5):
            self.assertIn(f"### Task {number} — ", text)
        self.assertIn("cloud_verification: not-run", text)
        self.assertIn("guide_status: authoring", text)


if __name__ == "__main__":
    unittest.main()
