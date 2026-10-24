"""Static quality checks for the runnable Lab 09 Thai guide."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit
import unittest


ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT / "GCP" / "LAB-009-partner-webhook-delivery" / "README.md"


class Lab09GuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = GUIDE.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_thirteen_ordered_tasks_have_recording_fields(self):
        tasks = {}
        active = None
        for line in self.lines:
            if line.startswith("### Task "):
                active = line[9:11]
                tasks[active] = []
            elif active is not None:
                tasks[active].append(line)
        self.assertEqual(list(tasks), [f"{n:02d}" for n in range(13)])
        for task_id, lines in tasks.items():
            content = chr(10).join(lines)
            self.assertIn("**Expected:**", content, task_id)
            self.assertIn("**Actual / Status / UTC:**", content, task_id)
            self.assertIn("**Evidence:**", content, task_id)

    def test_bash_fences_parse_without_running_cloud_commands(self):
        tick = chr(96) * 3
        blocks = []
        in_bash = False
        current = []
        for line in self.lines:
            if line == tick + "bash":
                self.assertFalse(in_bash, "nested bash fence")
                in_bash = True
                current = []
            elif line == tick and in_bash:
                blocks.append(chr(10).join(current) + chr(10))
                in_bash = False
            elif in_bash:
                current.append(line)
        self.assertFalse(in_bash, "unclosed bash fence")
        self.assertGreaterEqual(len(blocks), 15)
        for index, block in enumerate(blocks, 1):
            result = subprocess.run(
                ["bash", "-n"], input=block, text=True, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 0, f"bash block {index}: {result.stderr}")

    def test_guide_assets_and_private_terraform_files_are_present(self):
        for relative in (
            "assets/solution.svg",
            "assets/delivery-flow.svg",
            "infra/main.tf",
            "infra/variables.tf",
            "infra/terraform.tfvars.example",
            "Dockerfile",
            "app/operator_cli.py",
        ):
            self.assertTrue((GUIDE.parent / relative).is_file(), relative)
        self.assertIn("](assets/solution.svg)", self.text)
        self.assertIn("](assets/delivery-flow.svg)", self.text)
        ignored = (GUIDE.parent / "infra" / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("*.tfstate", ignored)
        self.assertIn("*.tfvars", ignored)
        self.assertIn("*.tfplan", ignored)
        self.assertIn("!*.tfvars.example", ignored)

    def test_local_markdown_links_resolve_to_repository_files(self):
        pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
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
            candidate = (GUIDE.parent / relative_path) if relative_path else GUIDE
            self.assertTrue(candidate.resolve().is_file(), target)

    def test_guide_and_cloud_status_are_not_conflated(self):
        front_matter = self.text.split("---", 2)[1]
        self.assertIn("guide_status: guide-ready", front_matter)
        self.assertIn("cloud_verification: not-run", front_matter)
        self.assertIn("Cloud verification: Not run", self.text)


if __name__ == "__main__":
    unittest.main()
