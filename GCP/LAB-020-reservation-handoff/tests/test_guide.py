from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class Lab020GuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_all_tasks_have_expected_and_recording_fields(self):
        ids = re.findall(r"(?m)^### Task T(\d{2}) — ", self.readme)
        self.assertEqual(ids, [f"{i:02d}" for i in range(18)])
        tasks = re.split(r"(?m)^### Task T\d{2} — ", self.readme)[1:]
        self.assertEqual(len(tasks), 18)
        for task in tasks:
            self.assertIn("**ผลที่คาดหวัง:**", task)
            self.assertIn("**บันทึกจริง / หลักฐาน:**", task)

    def test_bash_examples_parse_without_running(self):
        blocks = re.findall(r"(?ms)^~~~bash[ \t]*\n(.*?)^~~~[ \t]*$", self.readme)
        self.assertGreaterEqual(len(blocks), 20)
        for index, block in enumerate(blocks, start=1):
            result = subprocess.run(
                ["bash", "-n"], input=block, text=True, capture_output=True, check=False
            )
            self.assertEqual(result.returncode, 0, f"bash block {index}: {result.stderr}")

    def test_local_markdown_links_resolve(self):
        links = re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", self.readme)
        for target in links:
            local = target.split("#", 1)[0]
            if not local or "://" in local or local.startswith("mailto:"):
                continue
            resolved = (README.parent / local).resolve()
            self.assertTrue(resolved.is_file(), f"Broken README link: {target}")

    def test_cloud_build_uses_repository_root_and_cr_patch_order(self):
        guide = self.readme
        self.assertIn('--config=GCP/LAB-020-reservation-handoff/cloudbuild.yaml', guide)
        self.assertIn('cd "$REPO_ROOT"', guide)
        t16 = guide.split('### Task T16 —', 1)[1].split('### Task T17 —', 1)[0]
        self.assertLess(t16.index("python -m unittest discover -s tests -p 'test_release.py'"), t16.index('git -C "$REPO_ROOT" apply --directory=GCP/LAB-020-reservation-handoff GCP/'))
        self.assertIn("terraform -chdir=infra/runtime workspace select stage", t16)
        self.assertIn("terraform -chdir=infra/runtime workspace select prod", t16)
        self.assertIn("migration_image_digest=$CR_IMAGE_DIGEST", t16)
        self.assertIn("support_desk", t16)
        self.assertIn("ยังไม่มีการตรวจ Support role", t16)

    def test_cloud_results_are_not_claimed(self):
        self.assertIn("Cloud verification:** Not run", self.readme)
        self.assertIn("Expected output เป็นตัวอย่าง", self.readme)
        self.assertIn("ไม่ถือ Expected เป็น PASS หรือ Cloud proof", self.readme)


if __name__ == "__main__":
    unittest.main()
