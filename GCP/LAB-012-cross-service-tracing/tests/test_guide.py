"""Guide order, evidence prompts, local links and bash syntax checks."""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


class Lab12GuideTests(unittest.TestCase):
    def test_twenty_sequential_tasks_each_have_expected_actual_and_evidence(self):
        matches = list(re.finditer(r"(?m)^### Task (\d{2}) — .+$", README))
        self.assertEqual([int(match.group(1)) for match in matches], list(range(20)))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else README.find("\n## ", match.end())
            if end < 0:
                end = len(README)
            section = README[match.end():end]
            self.assertIn("สิ่งที่คาดว่าจะเห็น (Expected)", section, match.group(0))
            self.assertIn("ผลจริงที่ฉันบันทึก", section, match.group(0))
            self.assertIn("หลักฐานที่เก็บ", section, match.group(0))

    def test_all_bash_blocks_parse_without_running_cloud_commands(self):
        blocks = re.findall(
            r"(?m)^\*\*คำสั่ง Bash:\*\*\n(?:\n)?((?:^    [^\n]*\n?)+)",
            README,
        )
        self.assertGreaterEqual(len(blocks), 15)
        for index, block in enumerate(blocks):
            result = subprocess.run(
                ["bash", "-n"],
                input=textwrap.dedent(block),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, f"bash block {index}: {result.stderr}\n{block}")

    def test_local_markdown_links_resolve(self):
        prose = "\n".join(line for line in README.splitlines() if not line.startswith("    "))
        for match in re.finditer(r"\]\(([^)]+)\)", prose):
            target = match.group(1).strip()
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0].split(" ", 1)[0]
            if path:
                self.assertTrue((ROOT / path).resolve().is_file(), target)

    def test_no_fake_cloud_success_is_written(self):
        self.assertIn("phase: guide-ready", README)
        self.assertIn("guide_status: guide-ready", README)
        self.assertIn("cloud_verification: not-run", README)
        self.assertIn("Cloud verification: Not run", README)
        self.assertIn("Actual", README)
        self.assertIn("Cloud-verified", README)


if __name__ == "__main__":
    unittest.main()
