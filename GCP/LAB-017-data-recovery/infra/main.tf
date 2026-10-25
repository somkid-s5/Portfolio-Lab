locals {
  enabled_apis = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "serviceusage.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
  ])
  labels = {
    lab        = "lab017"
    managed_by = "terraform"
  }
}

resource "google_project_service" "enabled" {
  for_each                   = local.enabled_apis
  project                    = var.project_id
  service                    = each.value
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_compute_network" "lab" {
  name                    = "lab017-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "Private network for the Lab 17 recovery solution."
  depends_on              = [google_project_service.enabled]
}

resource "google_compute_subnetwork" "run_egress" {
  name                     = "lab017-run-egress"
  region                   = var.region
  network                  = google_compute_network.lab.id
  ip_cidr_range            = "10.90.1.0/26"
  private_ip_google_access = true
  description              = "Direct VPC egress subnet for Cloud Run to reach private Cloud SQL."
}

resource "google_compute_global_address" "psa_range" {
  name          = "lab017-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = "10.90.16.0"
  prefix_length = 20
  network       = google_compute_network.lab.id
  description   = "Reserved private services access range for Cloud SQL."
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.lab.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
  depends_on              = [google_project_service.enabled]
}

resource "google_sql_database_instance" "primary" {
  name                        = "lab017-primary"
  region                      = var.region
  database_version            = "POSTGRES_16"
  deletion_protection         = false

  settings {
    tier                  = var.db_tier
    edition               = "ENTERPRISE"
    availability_type     = "ZONAL"
    disk_type             = "PD_SSD"
    disk_size             = 20
    disk_autoresize       = true
    disk_autoresize_limit = 100
    user_labels           = local.labels

    backup_configuration {
      enabled                        = true
      start_time                     = var.backup_start_time
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 1

      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.lab.id
      enable_private_path_for_google_cloud_services = true
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_service_networking_connection.private_services,
  ]
}

resource "google_sql_database" "records" {
  name      = "records"
  instance  = google_sql_database_instance.primary.name
  charset   = "UTF8"
  collation = "en_US.UTF8"
}

resource "google_storage_bucket" "attachments" {
  name                        = var.bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels

  soft_delete_policy {
    retention_duration_seconds = 604800
  }

  versioning {
    enabled = false
  }

  depends_on = [google_project_service.enabled]
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "lab017"
  description   = "Container images for the Lab 17 Records API."
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.enabled]
}

resource "google_service_account" "run_runtime" {
  account_id   = "lab017-run-runtime"
  display_name = "Lab 17 Records API runtime"
  description  = "Cloud Run runtime identity with create/read-only attachment access."
  depends_on   = [google_project_service.enabled]
}

resource "google_project_iam_member" "runtime_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.run_runtime.email}"
}

resource "google_storage_bucket_iam_member" "runtime_create" {
  bucket = google_storage_bucket.attachments.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.run_runtime.email}"
}

resource "google_storage_bucket_iam_member" "runtime_read" {
  bucket = google_storage_bucket.attachments.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.run_runtime.email}"
}

resource "google_secret_manager_secret" "db_password" {
  secret_id = "lab017-db-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret" "db_admin_password" {
  secret_id = "lab017-db-admin-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_db_password" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run_runtime.email}"
}
