from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = (ROOT / "infra" / "foundation" / "main.tf").read_text(encoding="utf-8")
RUNTIME = (ROOT / "infra" / "runtime" / "main.tf").read_text(encoding="utf-8")
SCHEMA = (ROOT / "app" / "database_schema.py").read_text(encoding="utf-8")
API = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
WORKER = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")


class Lab020InfrastructureContracts(unittest.TestCase):
    def test_foundation_is_private_iam_authenticated_and_cost_bounded(self):
        for expected in (
            'database_version = "POSTGRES_16"',
            'availability_type = "ZONAL"',
            'ipv4_enabled = false',
            'ssl_mode = "ENCRYPTED_ONLY"',
            'point_in_time_recovery_enabled = true',
            '"cloudsql.iam_authentication"',
            '"roles/cloudsql.client"',
            '"roles/cloudsql.instanceUser"',
            'database_roles = ["cloudsqlsuperuser"]',
            'purpose = "VPC_PEERING"',
            'ip_cidr_range = "10.96.0.0/26"',
            'backend "gcs" {}',
        ):
            self.assertIn(expected, FOUNDATION)

    def test_runtime_separates_environments_and_authentication(self):
        self.assertIn('terraform.workspace == var.environment', RUNTIME)
        self.assertIn('iap_enabled = var.iap_enabled', RUNTIME)
        self.assertIn('count = var.iap_enabled ? 1 : 0', RUNTIME)
        self.assertEqual(RUNTIME.count('egress = "PRIVATE_RANGES_ONLY"'), 3)
        self.assertIn('max_instance_count = 2', RUNTIME)
        self.assertIn('max_instance_count = 3', RUNTIME)
        self.assertIn('public_access_prevention = "enforced"', RUNTIME)
        self.assertIn('uniform_bucket_level_access = true', RUNTIME)
        self.assertIn('versioning { enabled = true }', RUNTIME)
        self.assertIn('force_destroy = false', RUNTIME)
        self.assertIn('image_digest', RUNTIME)
        self.assertIn('migration_image_digest', RUNTIME)
        self.assertIn('sha256:', RUNTIME)
        self.assertNotIn('"allUsers"', RUNTIME)
        self.assertEqual(RUNTIME.count('invoker_iam_disabled = false'), 2)

    def test_pubsub_uses_oidc_retry_dead_letter_and_bounded_operator_tools(self):
        for expected in ('oidc_token', 'service_account_email = local.push_sa',
                         'dead_letter_policy', 'max_delivery_attempts = 5',
                         'minimum_backoff = "10s"', 'maximum_backoff = "60s"',
                         'google_pubsub_subscription.dead_letter_reader'):
            self.assertIn(expected, RUNTIME)
        redrive = (ROOT / "scripts" / "redrive_dlq.py").read_text(encoding="utf-8")
        self.assertIn('args.max_messages <= 5', redrive)
        recovery = (ROOT / "scripts" / "restore_object_generation.py").read_text(encoding="utf-8")
        self.assertIn('if_generation_match=destination_generation', recovery)
        self.assertIn('if not apply:', recovery)
        self.assertIn('MAX_BYTES = 5 * 1024 * 1024', recovery)

    def test_database_roles_are_separate_and_api_can_adjust_capacity(self):
        self.assertIn('GRANT SELECT, UPDATE ON slots TO {api}', SCHEMA)
        self.assertIn('GRANT SELECT, INSERT, UPDATE ON bookings TO {api}', SCHEMA)
        self.assertIn('GRANT SELECT ON bookings TO {worker}', SCHEMA)
        self.assertIn('GRANT SELECT, UPDATE ON report_jobs TO {worker}', SCHEMA)
        self.assertNotIn('ALTER DEFAULT PRIVILEGES', SCHEMA)
        self.assertNotIn('"created_by":', API)
        self.assertIn('"actor_hash"', API)
        self.assertNotIn('created_by', WORKER.split('writer.writerow', 1)[1])


if __name__ == "__main__":
    unittest.main()
