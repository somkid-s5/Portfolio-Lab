"""Static quality checks for the runnable Lab 10 Thai guide."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "README.md"


class Lab10GuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = GUIDE.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_fifteen_ordered_tasks_have_expected_actual_and_evidence_fields(self):
        tasks = {}
        active = None
        for line in self.lines:
            if line.startswith("### Task "):
                active = line[9:11]
                tasks[active] = []
            elif active is not None:
                tasks[active].append(line)
        self.assertEqual(list(tasks), [f"{number:02d}" for number in range(15)])
        for task_id, lines in tasks.items():
            content = chr(10).join(lines)
            self.assertIn("**Expected:**", content, task_id)
            self.assertIn("**Actual / Status / UTC:**", content, task_id)
            self.assertIn("**Evidence:**", content, task_id)

    def test_bash_blocks_parse_without_running_cloud_commands(self):
        fence = chr(96) * 3
        blocks = []
        in_bash = False
        current = []
        for line in self.lines:
            if line == fence + "bash":
                self.assertFalse(in_bash, "nested bash fence")
                in_bash = True
                current = []
            elif line == fence and in_bash:
                blocks.append(chr(10).join(current) + chr(10))
                in_bash = False
            elif in_bash:
                current.append(line)
        self.assertFalse(in_bash, "unclosed bash fence")
        self.assertGreaterEqual(len(blocks), 18)
        for index, block in enumerate(blocks, 1):
            result = subprocess.run(
                ["bash", "-n"], input=block, text=True, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 0, f"bash block {index}: {result.stderr}")

    def test_guide_links_and_required_assets_resolve(self):
        for relative in (
            "assets/solution.svg",
            "assets/cache-flow.svg",
            "assets/diagram-provenance.json",
            "infra/main.tf",
            "infra/variables.tf",
            "infra/terraform.tfvars.example",
            "cloudbuild.yaml",
            ".dockerignore",
            "scripts/run_load.py",
            "app/factory.py",
            "tests/test_app.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

        pattern = re.compile(r"\]\(([^)]+)\)")
        for match in pattern.finditer(self.text):
            target = match.group(1).strip()
            if target.startswith("<") and ">" in target:
                target = target[1:target.index(">")]
            else:
                target = target.split(" ", 1)[0]
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            if not parsed.path and parsed.fragment:
                continue
            relative_path = unquote(parsed.path)
            candidate = (ROOT / relative_path) if relative_path else GUIDE
            self.assertTrue(candidate.resolve().is_file(), target)

    def test_cloud_and_guide_status_remain_distinct(self):
        front_matter = self.text.split("---", 2)[1]
        self.assertIn("guide_status: authoring", front_matter)
        self.assertIn("cloud_verification: not-run", front_matter)
        self.assertIn("Cloud verification: Not run", self.text)
        self.assertIn("Case-study claim status:** " + chr(96) + "Not run" + chr(96), self.text)
        self.assertNotIn("Cloud verification: PASS", self.text)

    def test_workload_and_cleanup_contracts_stay_bounded_and_reversible(self):
        for phrase in (
            "cache_enabled = false",
            "simulate_redis_failure = true",
            "category_list_ttl_seconds = 15",
            "--requests 200",
            "--workers 5",
            "--seed 20261024",
            "lab10-results/experiment-01",
            "lifecycle.prevent_destroy",
            "plan -destroy",
            "-auto-approve",
            "ไม่ใช้ wildcard หรือ recursive delete",
        ):
            self.assertIn(phrase, self.text)
        self.assertIn("inspect_list_ttl", (ROOT / "app" / "cache.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
