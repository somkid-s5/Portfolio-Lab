from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class LabGuideContractTests(unittest.TestCase):
    def test_tasks_are_contiguous_and_have_recording_fields(self):
        text = README.read_text(encoding="utf-8")
        tasks = list(re.finditer(r"^### Task (\d{2}) — .+$", text, re.MULTILINE))
        self.assertEqual([match.group(1) for match in tasks], [f"{number:02d}" for number in range(16)])
        for index, match in enumerate(tasks):
            end = tasks[index + 1].start() if index + 1 < len(tasks) else text.find("\n## Troubleshooting", match.end())
            section = text[match.start():end]
            with self.subTest(task=match.group(1)):
                self.assertIn("**Expected:**", section)
                self.assertIn("**Actual", section)
                self.assertIn("**Evidence:**", section)

    def test_guide_keeps_cloud_state_explicit_and_links_local_assets(self):
        text = README.read_text(encoding="utf-8")
        self.assertRegex(text, r"guide_status: (authoring|guide-ready)")
        self.assertIn("cloud_verification: not-run", text)
        self.assertIn("สถานะ Cloud:** Not run", text)
        links = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text)
        for target in links:
            if "://" in target or target.startswith("#"):
                continue
            path = ROOT / target.split("#", 1)[0]
            with self.subTest(link=target):
                self.assertTrue(path.exists(), f"missing local README link: {target}")

    def test_command_fences_are_balanced(self):
        fences = re.findall(r"^\s*~~~[^\n]*$", README.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertEqual(len(fences) % 2, 0)


if __name__ == "__main__":
    unittest.main()
