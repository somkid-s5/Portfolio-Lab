from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
MAIN = (INFRA / "main.tf").read_text(encoding="utf-8")
VERSIONS = (INFRA / "versions.tf").read_text(encoding="utf-8")


class Lab017InfraContracts(unittest.TestCase):
    def test_provider_and_required_apis_are_pinned_and_enabled(self):
        self.assertIn('version = "= 7.29.0"', VERSIONS)
        for api in (
            "artifactregistry.googleapis.com", "cloudbuild.googleapis.com",
            "compute.googleapis.com", "run.googleapis.com",
            "secretmanager.googleapis.com", "servicenetworking.googleapis.com",
            "sqladmin.googleapis.com", "storage.googleapis.com",
        ):
            self.assertIn(f'"{api}"', MAIN)

    def test_database_is_postgres16_private_with_backup_and_pitr(self):
        self.assertIn('database_version    = "POSTGRES_16"', MAIN)
        self.assertIn("ipv4_enabled                                  = false", MAIN)
        self.assertIn("google_compute_network.lab.id", MAIN)
        self.assertIn("point_in_time_recovery_enabled = true", MAIN)
        self.assertIn("transaction_log_retention_days = 1", MAIN)
        self.assertIn("retained_backups = 7", MAIN)
        self.assertIn("google_service_networking_connection.private_services", MAIN)
        self.assertIn("deletion_protection = false", MAIN)
        self.assertNotIn("deletion_protection_enabled", MAIN)

    def test_storage_is_regional_private_and_soft_deleted(self):
        self.assertIn("location                    = var.region", MAIN)
        self.assertIn("uniform_bucket_level_access = true", MAIN)
        self.assertIn('public_access_prevention    = "enforced"', MAIN)
        self.assertIn("retention_duration_seconds = 604800", MAIN)
        self.assertIn("force_destroy               = false", MAIN)
        self.assertIn("versioning {\n    enabled = false", MAIN)

    def test_runtime_identity_can_create_and_read_but_not_delete_objects(self):
        self.assertIn('"roles/storage.objectCreator"', MAIN)
        self.assertIn('"roles/storage.objectViewer"', MAIN)
        self.assertNotIn('"roles/storage.objectAdmin"', MAIN)
        self.assertNotIn('"roles/storage.objectUser"', MAIN)
        schema = (ROOT / "app" / "schema.sql").read_text(encoding="utf-8")
        self.assertIn("GRANT SELECT, INSERT, UPDATE ON TABLE public.records TO records_app", schema)
        self.assertNotIn("GRANT DELETE", schema)
        self.assertIn('"roles/secretmanager.secretAccessor"', MAIN)
        self.assertIn('resource "google_secret_manager_secret" "db_admin_password"', MAIN)
        self.assertNotIn("google_secret_manager_secret_version", MAIN)
        self.assertIn('resource "google_secret_manager_secret_iam_member" "runtime_reads_db_password"', MAIN)


if __name__ == "__main__":
    unittest.main()
