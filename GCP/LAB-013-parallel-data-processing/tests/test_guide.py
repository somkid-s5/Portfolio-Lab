from __future__ import annotations

from pathlib import Path
import re
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


class Lab13GuideTests(unittest.TestCase):
    def test_twenty_ordered_tasks_include_expected_actual_and_evidence_fields(self):
        matches = list(re.finditer(r"(?m)^### Task (\d{2}) — .+$", README))
        self.assertEqual([int(match.group(1)) for match in matches], list(range(20)))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else README.find("\n## ", match.end())
            if end < 0:
                end = len(README)
            section = README[match.end():end]
            for phrase in ("สิ่งที่คาดว่าจะเห็น (Expected)", "ผลจริงที่ฉันบันทึก", "หลักฐานที่เก็บ"):
                self.assertIn(phrase, section, match.group(0))

    def test_every_guide_bash_block_parses_without_running_cloud_commands(self):
        blocks = re.findall(
            r"(?m)^\*\*คำสั่ง Bash:\*\*\n(?:\n)?((?:^    [^\n]*\n?)+)",
            README,
        )
        self.assertGreaterEqual(len(blocks), 15)
        for index, block in enumerate(blocks):
            result = subprocess.run(
                ["bash", "-n"], input=textwrap.dedent(block), text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, f"bash block {index}: {result.stderr}\n{block}")

    def test_cloud_build_source_excludes_state_and_lab_evidence(self):
        ignore = (ROOT / ".gcloudignore").read_text(encoding="utf-8")
        for entry in ("infra/", "work/", "tests/", "**/terraform.tfvars", "**/*.tfstate", "**/*.tfplan"):
            self.assertIn(entry, ignore)

    def test_recovery_change_and_cleanup_are_self_contained_and_guarded(self):
        recovery = README.split("### Task 16", 1)[1].split("### Task 17", 1)[0]
        change = README.split("### Task 17", 1)[1].split("### Task 18", 1)[0]
        cleanup = README.split("### Task 19", 1)[1].split("## Troubleshooting", 1)[0]
        for section, run_id, job_id in ((recovery, "RECOVERY_RUN_ID", "RECOVERY_JOB_ID"),
                                        (change, "CR_RUN_ID", "CR_JOB_ID")):
            self.assertIn("gcloud batch tasks list", section)
            self.assertIn("python3 tools/reconcile.py", section)
            self.assertIn(run_id, section)
            self.assertIn(job_id, section)
        self.assertIn("DELETE $run_id", cleanup)
        self.assertIn("gcloud storage rm --recursive", cleanup)

    def test_repository_relative_links_resolve_and_status_is_user_editable(self):
        prose = "\n".join(line for line in README.splitlines() if not line.startswith("    "))
        for match in re.finditer(r"\]\(([^)]+)\)", prose):
            target = match.group(1).strip()
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0].split(" ", 1)[0]
            if path:
                self.assertTrue((ROOT / path).resolve().is_file(), target)
        self.assertIn("guide_status: guide-ready", README)
        self.assertRegex(README, r"(?m)^cloud_verification: (not-run|in-progress|verified|failed|blocked)$")
        self.assertIn("Cloud verification:", README)
        self.assertIn("Repository CI เป็น code/documentation test ไม่ใช่ Cloud verification.", README)


if __name__ == "__main__":
    unittest.main()
