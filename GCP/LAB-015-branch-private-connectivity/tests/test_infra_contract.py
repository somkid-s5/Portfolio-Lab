from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
VARS = (ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")
VERSIONS = (ROOT / "infra" / "versions.tf").read_text(encoding="utf-8")


class InfrastructureContractTests(unittest.TestCase):
    def test_terraform_version_supports_write_only_arguments(self):
        self.assertIn('required_version = ">= 1.11.0, < 2.0.0"', VERSIONS)

    def test_private_vpcs_and_proxy_only_scope(self):
        for phrase in (
            'name                    = "lab015-hub-vpc"',
            'name                    = "lab015-branch-vpc"',
            'ip_cidr_range            = "10.60.0.0/24"',
            'ip_cidr_range            = "10.70.0.0/24"',
            'ip_cidr_range = "10.60.1.0/26"',
            'purpose       = "REGIONAL_MANAGED_PROXY"',
            'role          = "ACTIVE"',
        ):
            self.assertIn(phrase, MAIN)

    def test_dual_tunnel_bgp_failover_and_custom_prefixes(self):
        self.assertIn("simulate_tunnel_a_failure", MAIN)
        self.assertIn("active_tunnel_pairs", MAIN)
        self.assertIn('resource "google_compute_router_peer"', MAIN)
        self.assertIn('advertise_mode     = "CUSTOM"', MAIN)
        self.assertIn('hub_advertised_ranges    = ["10.60.0.0/24"]', MAIN)
        self.assertIn('"10.70.0.0/24", var.branch_additional_cidr', MAIN)
        self.assertIn("shared_secret_wo", MAIN)
        self.assertIn("shared_secret_wo_version", MAIN)

    def test_probe_vm_has_no_public_ip_and_egress_is_restricted(self):
        self.assertNotIn("access_config", MAIN)
        self.assertIn('source_ranges = ["35.235.240.0/20"]', MAIN)
        self.assertIn('destination_ranges = ["10.60.0.10/32"]', MAIN)
        self.assertIn('ports    = ["80"]', MAIN)
        self.assertIn('deny {\n    protocol = "all"', MAIN)

    def test_cloud_run_is_private_and_iam_is_service_scoped(self):
        self.assertIn('ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"', MAIN)
        self.assertIn('resource "google_cloud_run_v2_service_iam_member" "branch_invoker"', MAIN)
        self.assertNotIn('resource "google_project_iam_member" "branch_invoker"', MAIN)
        self.assertNotIn("allUsers", MAIN)
        self.assertIn("google_compute_region_network_endpoint_group", MAIN)
        self.assertIn('load_balancing_scheme = "INTERNAL_MANAGED"', MAIN)

    def test_dns_scope_and_change_request_are_explicit(self):
        self.assertIn("authorize_branch_dns", MAIN)
        self.assertIn("google_dns_managed_zone", MAIN)
        self.assertIn('resource "google_compute_subnetwork" "branch_change"', MAIN)
        self.assertIn('var.branch_additional_cidr == "10.70.1.0/24"', VARS)
        change_probe = MAIN.split('resource "google_compute_instance" "branch_change_probe" {', 1)[1].split("\n}", 1)[0]
        self.assertIn("google_service_account_iam_member.operator_act_as", change_probe)

    def test_cloud_build_identity_and_repository_scoped_permissions(self):
        cloudbuild = (ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
        self.assertIn("serviceAccount: projects/$PROJECT_ID/serviceAccounts/lab015-builder@", cloudbuild)
        self.assertIn("logging: CLOUD_LOGGING_ONLY", cloudbuild)
        self.assertIn('resource "google_artifact_registry_repository_iam_member" "builder_writer"', MAIN)
        self.assertIn('role       = "roles/artifactregistry.writer"', MAIN)
        self.assertIn('resource "google_service_account_iam_member" "cloudbuild_act_as_builder"', MAIN)
        self.assertIn('role               = "roles/iam.serviceAccountUser"', MAIN)
        gcloudignore = (ROOT / ".gcloudignore").read_text(encoding="utf-8")
        for pattern in ("**/*.tfstate", "**/*.tfplan", "**/terraform.tfvars", "**/.env"):
            self.assertIn(pattern, gcloudignore)


if __name__ == "__main__":
    unittest.main()
