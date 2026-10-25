# Foundation only. Image, secret versions and Cloud Run revisions are CLI-owned.
# Never put password values or secret_version resources in Terraform state.
locals {
  apis = toset([
    "compute.googleapis.com", "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com", "run.googleapis.com",
    "secretmanager.googleapis.com", "artifactregistry.googleapis.com",
    "iam.googleapis.com", "cloudresourcemanager.googleapis.com"
  ])
  secret_names = toset(["auth", "db-a", "db-b", "bootstrap-admin"])
}
resource "google_project_service" "api" {
  for_each = local.apis
  service = each.value
  disable_on_destroy = false
}
resource "google_compute_network" "booking" {
  name = "lab004-vpc"
  auto_create_subnetworks = false
  depends_on = [google_project_service.api]
}
resource "google_compute_subnetwork" "run" {
  name = "lab004-run-subnet"
  region = var.region
  network = google_compute_network.booking.id
  ip_cidr_range = "10.44.0.0/24"
  private_ip_google_access = true
}
# This allocated producer range is not a workload subnet.
resource "google_compute_global_address" "sql" {
  name = "lab004-sql-psa"
  purpose = "VPC_PEERING"
  address_type = "INTERNAL"
  address = "10.84.0.0"
  prefix_length = 16
  network = google_compute_network.booking.id
}
resource "google_service_networking_connection" "sql" {
  network = google_compute_network.booking.id
  service = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql.name]
}
resource "google_sql_database_instance" "booking" {
  name = "lab004-sql"
  database_version = "POSTGRES_16"
  region = var.region
  deletion_protection = !var.allow_destroy
  depends_on = [google_service_networking_connection.sql]
  settings {
    tier = "db-custom-1-3840"
    edition = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type = "PD_SSD"
    disk_size = 10
    disk_autoresize = false
    deletion_protection_enabled = !var.allow_destroy
    user_labels = { lab = "lab004", purpose = "training" }
    ip_configuration {
      ipv4_enabled = false
      private_network = google_compute_network.booking.id
      allocated_ip_range = google_compute_global_address.sql.name
      ssl_mode = "ENCRYPTED_ONLY"
    }
    database_flags {
      name = "max_connections"
      value = "40"
    }
    backup_configuration {
      enabled = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 1
      start_time = "18:00"
      backup_retention_settings {
        retained_backups = 2
        retention_unit = "COUNT"
      }
    }
  }
}
resource "google_sql_database" "booking" {
  name = "booking"
  instance = google_sql_database_instance.booking.name
}
resource "google_artifact_registry_repository" "images" {
  location = var.region
  repository_id = "lab004-images"
  format = "DOCKER"
  depends_on = [google_project_service.api]
}
resource "google_service_account" "runtime" {
  account_id = "lab004-runtime"
  display_name = "Lab004 booking runtime"
  depends_on = [google_project_service.api]
}
resource "google_service_account" "bootstrap" {
  account_id = "lab004-bootstrap"
  display_name = "Lab004 one-time DB initializer"
  depends_on = [google_project_service.api]
}
resource "google_project_iam_member" "runtime_sql" {
  project = var.project_id
  role = "roles/cloudsql.client"
  member = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_project_iam_member" "bootstrap_sql" {
  project = var.project_id
  role = "roles/cloudsql.client"
  member = "serviceAccount:${google_service_account.bootstrap.email}"
}
resource "google_secret_manager_secret" "booking" {
  for_each = local.secret_names
  secret_id = "lab004-${each.value}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.api]
}
# A/B are both scoped DB-login secrets; the admin secret is NEVER runtime-readable.
resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each = toset(["auth", "db-a", "db-b"])
  secret_id = google_secret_manager_secret.booking[each.value].id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_secret_manager_secret_iam_member" "bootstrap" {
  for_each = toset(["bootstrap-admin", "db-a", "db-b"])
  secret_id = google_secret_manager_secret.booking[each.value].id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.bootstrap.email}"
}
