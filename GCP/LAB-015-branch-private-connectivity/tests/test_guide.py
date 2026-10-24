from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "README.md").read_text(encoding="utf-8")


class LabGuideTests(unittest.TestCase):
    def test_tasks_are_contiguous_and_record_expected_actual_evidence(self):
        tasks = list(re.finditer(r"^### Task (\d{2}) — .+$", TEXT, re.MULTILINE))
        self.assertEqual([m.group(1) for m in tasks], [f"{i:02d}" for i in range(16)])
        for index, match in enumerate(tasks):
            stop = tasks[index + 1].start() if index + 1 < len(tasks) else TEXT.find("\n## Troubleshooting", match.end())
            section = TEXT[match.start():stop]
            with self.subTest(task=match.group(1)):
                self.assertIn("**Expected:**", section)
                self.assertIn("**Actual:**", section)
                self.assertIn("**Evidence:**", section)

    def test_local_links_and_cloud_status_are_explicit(self):
        self.assertIn("guide_status: authoring", TEXT)
        self.assertIn("cloud_verification: not-run", TEXT)
        self.assertIn("สถานะ Cloud:** Not run", TEXT)
        links = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", TEXT)
        for target in links:
            if "://" in target or target.startswith("#"):
                continue
            self.assertTrue((ROOT / target.split("#", 1)[0]).exists(), target)

    def test_fences_and_primary_references(self):
        self.assertEqual(len(re.findall(r"^~~~[^\n]*$", TEXT, re.MULTILINE)) % 2, 0)
        self.assertIn("docs.cloud.google.com/network-connectivity/docs/vpn", TEXT)
        self.assertIn("registry.terraform.io/providers/hashicorp/google/7.29.0", TEXT)


if __name__ == "__main__":
    unittest.main()
