"""Static guide checks only: never execute README commands or contact GCP."""
import re
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

LAB = Path(__file__).resolve().parents[1]
REPO = LAB.parents[1]


class GuideTests(unittest.TestCase):
    def test_bash_examples_parse_without_execution(self):
        text = (LAB / "README.md").read_text(encoding="utf-8")
        blocks = re.findall(r"^```bash\n(.*?)^```\s*$", text, re.M | re.S)
        self.assertGreaterEqual(len(blocks), 40)
        for index, block in enumerate(blocks, 1):
            with self.subTest(block=index):
                result = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-n"],
                    input=block, text=True, capture_output=True, timeout=10,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_relative_links_resolve_inside_repository(self):
        text = (LAB / "README.md").read_text(encoding="utf-8")
        links = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text)
        self.assertGreater(len(links), 20)
        checked = 0
        for target in links:
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith("#"):
                continue
            with self.subTest(target=target):
                path = (LAB / unquote(parsed.path)).resolve()
                self.assertTrue(path.is_relative_to(REPO))
                self.assertTrue(path.is_file(), target)
                checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_recording_and_acceptance_sections_are_present(self):
        text = (LAB / "README.md").read_text(encoding="utf-8")
        for number in [*range(7), 8, 9, 10, 11, 12, 13, 14]:
            self.assertRegex(text, rf"(?m)^### Task {number} — ")
        for suffix in ("7A", "7B"):
            self.assertIn(f"### Task {suffix} — ", text)
        for number in range(1, 9):
            self.assertIn(f"| R{number} |", text)
        self.assertIn("cloud_verification: not-run", text)
        self.assertIn("assets/solution-preview.png", text)
        self.assertIn("assets/operations-preview.png", text)


if __name__ == "__main__":
    unittest.main()
