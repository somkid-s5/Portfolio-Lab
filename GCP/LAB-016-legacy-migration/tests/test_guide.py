from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
TEXT = README.read_text(encoding="utf-8")


class Lab016GuideContracts(unittest.TestCase):
    def test_task_sequence_and_portfolio_sections_are_complete(self):
        tasks = re.findall(r"^## Task (\d{2}) — ", TEXT, flags=re.MULTILINE)
        self.assertEqual(tasks, [f"{n:02d}" for n in range(14)])
        for section in (
            "Requirements และเกณฑ์รับงาน",
            "Solution",
            "Actual / Evidence",
            "Case-study summary",
            "Troubleshooting",
            "Rebuild",
            "Task 13 — Cleanup",
        ):
            self.assertIn(section, TEXT)

    def test_cloud_result_is_not_fabricated_and_evidence_is_distinct(self):
        self.assertIn("Cloud verification:** Not run", TEXT)
        self.assertIn("Actual / Evidence", TEXT)
        self.assertIn("Expected", TEXT)
        self.assertIn("ไม่ใช่ผล Cloud execution", TEXT)
        self.assertIn("rollback boundary", TEXT)

    def test_solution_flow_and_guardrails_are_documented(self):
        for marker in (
            "lab016-legacy-backend",
            "lab016-run-backend",
            "source-write-gate.sh freeze",
            "final-migrate.sh",
            "reconciliation.json",
            "ALLOW_WRITES=false",
            "internal-and-cloud-load-balancing",
            "private-ranges-only",
            "orders.lab.test",
            "No-go",
            "source.dump",
        ):
            self.assertIn(marker, TEXT)

    def test_local_diagrams_exist(self):
        for relative in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", TEXT):
            if "://" not in relative:
                self.assertTrue((ROOT / relative).is_file(), relative)

    def test_bash_examples_parse(self):
        blocks = re.findall(r"~~~bash\s*\n(.*?)\n~~~", TEXT, flags=re.DOTALL)
        self.assertGreaterEqual(len(blocks), 20)
        for index, block in enumerate(blocks, start=1):
            result = subprocess.run(
                ["bash", "-n"], input=block, text=True, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 0, f"Bash block {index}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
