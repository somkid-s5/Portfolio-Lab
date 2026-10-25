from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = (ROOT / "infra" / "foundation" / "main.tf").read_text(encoding="utf-8")
RUNTIME = (ROOT / "infra" / "runtime" / "main.tf").read_text(encoding="utf-8")


class Lab019InfrastructureContracts(unittest.TestCase):
    def test_foundation_is_private_iam_authenticated_and_cost_bounded(self):
        for expected in (
            'ipv4_enabled    = false',
            'name  = "cloudsql.iam_authentication"',
            'availability_type     = "ZONAL"',
            '"roles/cloudsql.client"',
            '"roles/cloudsql.instanceUser"',
            'database_roles = ["cloudsqlsuperuser"]',
            'ip_cidr_range            = "10.94.0.0/26"',
            'purpose       = "VPC_PEERING"',
            '"operator_act_as_runtime"',
        ):
            self.assertIn(expected, FOUNDATION)

    def test_runtime_uses_private_vpc_egress_and_no_public_invoker(self):
        self.assertEqual(RUNTIME.count('egress = "PRIVATE_RANGES_ONLY"'), 2)
        self.assertEqual(RUNTIME.count('invoker_iam_disabled = false'), 2)
        self.assertIn("max_instance_count = 2", RUNTIME)
        self.assertIn("max_instance_count = 3", RUNTIME)
        self.assertNotIn('"allUsers"', RUNTIME)
        self.assertNotIn("roles/run.invoker\".*allUsers", RUNTIME)
        self.assertIn("CLOUD_IAM_SERVICE_ACCOUNT", RUNTIME)
        self.assertIn('database_roles = ["lab19_api_role"]', RUNTIME)
        self.assertIn('database_roles = ["lab19_worker_role"]', RUNTIME)

    def test_push_subscription_authenticates_worker_and_has_recovery_path(self):
        for expected in (
            "oidc_token",
            "service_account_email = local.push_sa",
            "google_cloud_run_v2_service_iam_member.push_invokes_worker",
            "dead_letter_policy",
            "max_delivery_attempts = 5",
            "dead-letter-events",
            "google_pubsub_subscription.dead_letter_status",
            'resource "google_pubsub_subscription_iam_member" "pubsub_agent_reads_dlq_status"',
            "lab19_dead_lettered_tasks",
            'resource "google_pubsub_subscription_iam_member" "pubsub_agent_reads_source"',
            'resource "google_pubsub_topic_iam_member" "pubsub_agent_publishes_dlq"',
        ):
            self.assertIn(expected, RUNTIME)

    def test_user_sli_slos_and_alerts_are_defined(self):
        for expected in (
            "lab19_eligible_requests",
            "lab19_request_duration_ms",
            "rolling_period_days = 7",
            "goal                = 0.995",
            "goal                = 0.95",
            'select_slo_burn_rate',
            "24h",
            'oldest_unacked_message_age_by_region',
            'database/cpu/utilization',
            'service_agent_authentication',
            'type = "OIDC_TOKEN"',
        ):
            self.assertIn(expected, RUNTIME)

    def test_runtime_has_a_private_operator_state_boundary(self):
        self.assertIn("image_digest", RUNTIME)
        self.assertIn("sha256:", RUNTIME)
        self.assertIn("alert_email", RUNTIME)
        self.assertTrue((ROOT / "infra" / ".gitignore").is_file())
        self.assertIn("*.tfvars", (ROOT / "infra" / ".gitignore").read_text(encoding="utf-8"))

    def test_cr_baseline_alert_is_opt_in_and_uses_eligible_bad_metric(self):
        runtime_vars = (ROOT / "infra" / "runtime" / "main.tf").read_text(encoding="utf-8")
        example = (ROOT / "infra" / "runtime" / "terraform.tfvars.example").read_text(encoding="utf-8")
        self.assertIn('variable "cr_baseline_single_5xx_enabled"', runtime_vars)
        self.assertIn("default     = false", runtime_vars)
        self.assertIn("count                 = var.cr_baseline_single_5xx_enabled ? 1 : 0", runtime_vars)
        self.assertIn("metric.label.outcome", runtime_vars)
        self.assertIn("google_logging_metric.eligible_requests", runtime_vars)
        self.assertIn("cr_baseline_single_5xx_enabled = false", example)

    def test_custom_cloud_build_identity_uses_cloud_logging_only(self):
        build_config = (ROOT / "app" / "cloudbuild.yaml").read_text(encoding="utf-8")
        self.assertIn("CLOUD_LOGGING_ONLY", build_config)
        self.assertIn("$_IMAGE_URI", build_config)
        self.assertIn("docker", build_config)


if __name__ == "__main__":
    unittest.main()
