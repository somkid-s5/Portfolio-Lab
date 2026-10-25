from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class Lab019BriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")

    def test_title_status_and_cloud_boundary(self):
        self.assertIn("# Lab 19 — ระบบเฝ้าระวังและรับ Incident สำหรับทีมบริการ", self.readme)
        self.assertTrue("Guide review pending" in self.readme or "Guide-ready" in self.readme)
        self.assertIn("Cloud verification:** Not run", self.readme)
        self.assertIn("ไม่มีการ provision", self.readme)

    def test_requirements_are_numbered_and_cover_the_solution(self):
        ids = re.findall(r"^\| (R\d{2}) \|", self.readme, re.MULTILINE)
        self.assertEqual(ids, [f"R{i:02d}" for i in range(1, 15)])
        for phrase in ("Pub/Sub", "Cloud Run", "Cloud SQL", "SLO", "burn", "Incident", "Change Request"):
            self.assertIn(phrase, self.readme)

    def test_brief_architecture_and_change_request_are_preserved(self):
        for section in ("## Requirements", "## Architecture decisions", "## Change Request",
                        "## คู่มือทำ Solution Lab", "## References"):
            self.assertIn(section, self.readme)
        self.assertIn("single-zone", self.readme)
        self.assertIn("Cloud Trace", self.readme)
        self.assertIn("sampled", self.readme)

    def test_guide_tasks_follow_dependency_order(self):
        ids = re.findall(r"^### Task T(\d{2}) —", self.readme, re.MULTILINE)
        self.assertEqual(ids, [f"{i:02d}" for i in range(18)])
        self.assertIn("cr_baseline_single_5xx_enabled", self.readme)
        self.assertIn("CLOUD_LOGGING_ONLY", self.readme)
        self.assertIn("migration_status=applied", self.readme)

    def test_sli_slo_scope_and_noise_policy_are_explicit(self):
        for phrase in ("99.5%", "1,000 ms", "rolling 7 วัน", "10×", "24 ชั่วโมง",
                       "/healthz", "expected 4xx", "allUsers"):
            self.assertIn(phrase, self.readme)
        for url in (
            "https://docs.cloud.google.com/stackdriver/docs/solutions/slo-monitoring/sli-metrics/logs-based-metrics",
            "https://docs.cloud.google.com/monitoring/uptime-checks",
            "https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions",
            "https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc",
        ):
            self.assertIn(url, self.readme)


if __name__ == "__main__":
    unittest.main()
