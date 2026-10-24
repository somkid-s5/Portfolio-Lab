from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
SCRIPTS = ROOT / "scripts"
MAIN = (INFRA / "main.tf").read_text(encoding="utf-8")
VERSIONS = (INFRA / "versions.tf").read_text(encoding="utf-8")
STARTUP = (SCRIPTS / "source-startup.sh").read_text(encoding="utf-8")
DB_START = (SCRIPTS / "start-source-db.sh").read_text(encoding="utf-8")
DB_INIT = (SCRIPTS / "source-db-init.sh").read_text(encoding="utf-8")
APP_INSTALL = (SCRIPTS / "install-source-app.sh").read_text(encoding="utf-8")
WRITE_GATE = (SCRIPTS / "source-write-gate.sh").read_text(encoding="utf-8")


class Lab016InfraContracts(unittest.TestCase):
    def test_cloud_sql_is_private_same_region_and_deletable_for_cleanup(self):
        self.assertIn('database_version = "POSTGRES_16"', MAIN)
        self.assertIn('availability_type = "ZONAL"', MAIN)
        self.assertRegex(MAIN, r"ipv4_enabled\s*=\s*false")
        self.assertIn("google_compute_network.lab.id", MAIN)
        self.assertIn("google_compute_global_address.psa_range.name", MAIN)
        self.assertIn("deletion_protection = false", MAIN)
        self.assertIn('resource "google_service_networking_connection"', MAIN)
        self.assertIn("reserved_peering_ranges =", MAIN)

    def test_source_vm_has_no_external_nic_and_nat_is_scoped(self):
        instance = MAIN.split('resource "google_compute_instance" "source"')[1]
        self.assertNotIn("access_config", instance)
        self.assertIn('source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"', MAIN)
        self.assertIn("google_compute_subnetwork.source.id", MAIN)
        self.assertNotIn("ALL_SUBNETWORKS_ALL_IP_RANGES", MAIN)
        self.assertIn('"10.80.0.0/24"', MAIN)
        self.assertIn('"10.80.1.0/26"', MAIN)

    def test_firewalls_limit_ingress_to_iap_and_load_balancer(self):
        self.assertIn('"35.235.240.0/20"', MAIN)
        self.assertIn('"35.191.0.0/16", "130.211.0.0/22"', MAIN)
        self.assertIn('ports    = ["22"]', MAIN)
        self.assertIn('ports    = ["8080"]', MAIN)
        self.assertIn('target_tags   = ["lab016-source"]', MAIN)

    def test_secret_containers_and_scoped_iam(self):
        self.assertIn('resource "google_secret_manager_secret" "target_db_password"', MAIN)
        self.assertNotIn("google_secret_manager_secret_version", MAIN)
        self.assertIn('resource "google_secret_manager_secret_iam_member" "run_reads_target_db_password"', MAIN)
        self.assertIn('resource "google_secret_manager_secret_iam_member" "source_reads_target_db_password"', MAIN)
        self.assertIn('roles/cloudsql.client', MAIN)
        self.assertIn('roles/logging.logWriter', MAIN)

    def test_bootstrap_keeps_database_private_and_does_not_reset_existing_data(self):
        self.assertIn("docker.io", STARTUP)
        self.assertIn("google-cloud-ops-agent-repo.sh", STARTUP)
        self.assertIn("--publish 127.0.0.1:5432:5432", DB_START)
        self.assertIn("non-empty", DB_START)
        self.assertIn("CREATE ROLE orders_app", DB_INIT)
        self.assertIn("CREATE DATABASE orders OWNER orders_app", DB_INIT)
        self.assertIn("ALLOW_WRITES=true", APP_INSTALL)
        self.assertIn('case "${1:-}"', WRITE_GATE)

    def test_pinned_provider_and_no_committed_secret_value(self):
        self.assertRegex(VERSIONS, r'version\s*=\s*"= 7\.29\.0"')
        self.assertNotRegex(MAIN.lower(), r'(password\s*=\s*"[^"]+"|private_key\s*=)')
        self.assertIn("openssl rand -hex 32", DB_START)


if __name__ == "__main__":
    unittest.main()
