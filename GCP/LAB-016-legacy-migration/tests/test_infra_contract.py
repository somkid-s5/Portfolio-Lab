from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[1]
INFRA=ROOT/"infra"
SCRIPTS=ROOT/"scripts"
MAIN=(INFRA/"main.tf").read_text(encoding="utf-8")
VERSIONS=(INFRA/"versions.tf").read_text(encoding="utf-8")
STARTUP=(SCRIPTS/"source-startup.sh").read_text(encoding="utf-8")
DB_START=(SCRIPTS/"start-source-db.sh").read_text(encoding="utf-8")
APP_INSTALL=(SCRIPTS/"install-source-app.sh").read_text(encoding="utf-8")
class Lab016InfraContracts(unittest.TestCase):
 def test_cloud_sql_is_private_same_region_and_deletable_for_cleanup(self):
  self.assertIn('database_version = "POSTGRES_16"',MAIN)
  self.assertIn('availability_type = "ZONAL"',MAIN)
  self.assertIn('ipv4_enabled = false',MAIN)
  self.assertIn('private_network = google_compute_network.lab.id',MAIN)
  self.assertIn('allocated_ip_range = google_compute_global_address.psa_range.name',MAIN)
  self.assertIn('deletion_protection = false',MAIN)
  self.assertIn('google_service_networking_connection',MAIN)
  self.assertIn('reserved_peering_ranges = [google_compute_global_address.psa_range.name]',MAIN)
 def test_source_vm_has_no_external_nic_and_nat_is_scoped(self):
  instance=MAIN.split('resource "google_compute_instance" "source"')[1]
  self.assertNotIn("access_config",instance)
  self.assertIn('source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"',MAIN)
  self.assertIn('name = google_compute_subnetwork.source.id',MAIN)
  self.assertNotIn("ALL_SUBNETWORKS_ALL_IP_RANGES",MAIN)
  self.assertIn('"10.80.0.0/24"',MAIN); self.assertIn('"10.80.1.0/26"',MAIN)
 def test_firewalls_limit_ingress_to_iap_and_load_balancer(self):
  self.assertIn('"35.235.240.0/20"',MAIN)
  self.assertIn('"35.191.0.0/16", "130.211.0.0/22"',MAIN)
  self.assertIn('ports = ["22"]',MAIN); self.assertIn('ports = ["8080"]',MAIN)
  self.assertIn('target_tags = ["lab016-source"]',MAIN)
 def test_secrets_are_empty_containers_and_iam_is_resource_scoped(self):
  self.assertIn('resource "google_secret_manager_secret" "target_db_password"',MAIN)
  self.assertNotIn('google_secret_manager_secret_version',MAIN)
  self.assertIn('resource "google_secret_manager_secret_iam_member" "run_reads_target_db_password"',MAIN)
  self.assertIn('resource "google_secret_manager_secret_iam_member" "source_reads_target_db_password"',MAIN)
  self.assertIn('roles/cloudsql.client',MAIN); self.assertIn('roles/logging.logWriter',MAIN)
 def test_versions_and_no_plaintext_secret_values(self):
  self.assertRegex(VERSIONS,r'version\s*=\s*"= 7\.29\.0"')
  self.assertNotRegex(MAIN.lower(),r'(password\s*=\s*"[^"]+"|private_key\s*=)')
if __name__=="__main__": unittest.main()
