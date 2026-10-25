from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = (ROOT / "infra" / "foundation" / "main.tf").read_text(encoding="utf-8")
SEEDER = (ROOT / "infra" / "seeder" / "main.tf").read_text(encoding="utf-8")
FACTORY = (ROOT / "infra" / "factory" / "main.tf").read_text(encoding="utf-8")


class EnvironmentFactoryContracts(unittest.TestCase):
    def test_foundation_state_bucket_is_private_versioned_and_protected(self):
        for expected in (
            "uniform_bucket_level_access = true",
            'public_access_prevention    = "enforced"',
            "enabled = true",
            "prevent_destroy = true",
            '"roles/storage.objectAdmin"',
        ):
            self.assertIn(expected, FOUNDATION)

    def test_central_log_buckets_and_sink_writer_scopes_are_declared(self):
        self.assertIn("google_logging_project_bucket_config", FOUNDATION)
        self.assertIn('"roles/logging.logWriter"', FOUNDATION)
        self.assertIn('"roles/logging.bucketWriter"', FOUNDATION)
        self.assertIn("var.sink_writer_identities", FOUNDATION)

    def test_seeder_only_owns_project_lifecycle(self):
        self.assertIn("google_project.environment", SEEDER)
        self.assertIn('deletion_policy     = var.allow_project_delete ? "DELETE" : "PREVENT"', SEEDER)
        self.assertNotIn("google_project_iam_member", SEEDER)
        self.assertNotIn("roles/editor", SEEDER)

    def test_factory_budget_is_project_filtered_and_alert_only(self):
        self.assertIn("google_billing_budget", FACTORY)
        self.assertIn("google_project.current.number", FACTORY)
        self.assertIn("monitoring_notification_channels", FACTORY)
        self.assertIn("threshold_rules", FACTORY)

    def test_service_is_private_by_iam_and_image_digest_is_required(self):
        self.assertIn("invoker_iam_disabled = false", FACTORY)
        self.assertIn('"roles/run.invoker"', FACTORY)
        self.assertIn('"roles/run.viewer"', FACTORY)
        self.assertIn("sha256:", FACTORY)
        self.assertIn("deletion_protection  = !var.allow_destroy", FACTORY)
        self.assertNotIn('"allUsers"', FACTORY)
        self.assertIn("run.googleapis.com%2Fstdout", FACTORY)

    def test_each_root_has_a_pinned_provider_and_remote_backend(self):
        for folder in ("foundation", "seeder", "factory"):
            main = (ROOT / "infra" / folder / "main.tf").read_text(encoding="utf-8")
            self.assertIn('source  = "hashicorp/google"', main)
            self.assertIn('"= 7.29.0"', main)
            self.assertTrue((ROOT / "infra" / folder / "backend.tf").is_file())


if __name__ == "__main__":
    unittest.main()
