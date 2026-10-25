terraform {
  backend "gcs" {}
  required_version = ">= 1.9.8, < 2.0"
  required_providers {
    google      = { source = "hashicorp/google", version = "= 7.29.0" }
    google-beta = { source = "hashicorp/google-beta", version = "= 7.29.0" }
  }
}
provider "google" {
  project = var.project_id
  region  = var.region
}
provider "google-beta" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  description = "Dedicated billing-enabled Lab project; never use shared production."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Enter a valid Google Cloud project ID."
  }
}
variable "region" {
  description = "Single region used by this solution."
  type        = string
  default     = "asia-southeast1"
}
variable "operator_member" {
  description = "Human principal that applies Terraform and submits Cloud Build, e.g. user:name@example.com."
  type        = string
  validation {
    condition     = can(regex("^(user|group):[^@[:space:]]+@[^@[:space:]]+$", var.operator_member))
    error_message = "Use a complete user: or group: IAM member."
  }
}
variable "db_tier" {
  description = "Review the live regional price before applying."
  type        = string
  default     = "db-custom-1-3840"
}

locals {
  labels = { lab = "lab20", managed_by = "terraform" }
  required_services = toset([
    "artifactregistry.googleapis.com", "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com", "compute.googleapis.com",
    "iam.googleapis.com", "iamcredentials.googleapis.com", "iap.googleapis.com",
    "logging.googleapis.com", "monitoring.googleapis.com", "pubsub.googleapis.com",
    "run.googleapis.com", "servicenetworking.googleapis.com",
    "serviceusage.googleapis.com", "sqladmin.googleapis.com", "storage.googleapis.com"
  ])
  identities = toset([
    "api-stage", "worker-stage", "push-stage", "api-prod", "worker-prod",
    "push-prod", "migrator", "build"
  ])
  database_identities = {
    "api-stage"    = google_service_account.workload["api-stage"].email
    "worker-stage" = google_service_account.workload["worker-stage"].email
    "api-prod"     = google_service_account.workload["api-prod"].email
    "worker-prod"  = google_service_account.workload["worker-prod"].email
    "migrator"     = google_service_account.workload["migrator"].email
  }
}

data "google_project" "current" { project_id = var.project_id }

resource "google_project_service" "enabled" {
  for_each                   = local.required_services
  project                    = var.project_id
  service                    = each.value
  disable_on_destroy         = false
  disable_dependent_services = false
}
resource "google_project_service_identity" "pubsub" {
  project    = var.project_id
  service    = "pubsub.googleapis.com"
  depends_on = [google_project_service.enabled]
}
resource "google_project_service_identity" "iap" {
  project    = var.project_id
  service    = "iap.googleapis.com"
  depends_on = [google_project_service.enabled]
}

resource "google_compute_network" "lab" {
  name                    = "lab20-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "Private egress network for Lab 20 booking services."
  depends_on              = [google_project_service.enabled]
}
resource "google_compute_subnetwork" "run_egress" {
  name                     = "lab20-run-egress"
  region                   = var.region
  network                  = google_compute_network.lab.id
  ip_cidr_range            = "10.96.0.0/26"
  private_ip_google_access = true
  description              = "Direct VPC egress for API, worker, and schema migration job."
}
resource "google_compute_global_address" "psa_range" {
  name          = "lab20-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = "10.96.16.0"
  prefix_length = 20
  network       = google_compute_network.lab.id
}
resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.lab.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
  depends_on              = [google_project_service.enabled]
}

resource "google_sql_database_instance" "primary" {
  name                = "lab20-postgres"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = false
  settings {
    tier                  = var.db_tier
    edition               = "ENTERPRISE"
    availability_type     = "ZONAL"
    disk_type             = "PD_SSD"
    disk_size             = 20
    disk_autoresize       = true
    disk_autoresize_limit = 50
    user_labels           = local.labels
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 1
      start_time                     = "03:00"
      backup_retention_settings {
        retained_backups = 3
        retention_unit   = "COUNT"
      }
    }
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.lab.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
  }
  depends_on = [
    google_project_service.enabled,
    google_service_networking_connection.private_services
  ]
}
resource "google_sql_database" "environment" {
  for_each  = toset(["stage", "prod"])
  name      = "lab20_${each.value}"
  instance  = google_sql_database_instance.primary.name
  charset   = "UTF8"
  collation = "en_US.UTF8"
}
resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "lab20-apps"
  description   = "Container images for the Lab 20 booking solution."
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.enabled]
}
resource "google_service_account" "workload" {
  for_each     = local.identities
  account_id   = "lab20-${each.value}"
  display_name = "Lab 20 ${each.value} workload identity"
  description  = "Dedicated identity for the ${each.value} role."
  depends_on   = [google_project_service.enabled]
}

resource "google_project_iam_member" "sql_client" {
  for_each = local.database_identities
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${each.value}"
}
resource "google_project_iam_member" "sql_instance_user" {
  for_each = local.database_identities
  project  = var.project_id
  role     = "roles/cloudsql.instanceUser"
  member   = "serviceAccount:${each.value}"
}
resource "google_sql_user" "migrator" {
  project        = var.project_id
  name           = trimsuffix(google_service_account.workload["migrator"].email, ".gserviceaccount.com")
  instance       = google_sql_database_instance.primary.name
  type           = "CLOUD_IAM_SERVICE_ACCOUNT"
  database_roles = ["cloudsqlsuperuser"]
  depends_on     = [google_project_iam_member.sql_instance_user]
}
resource "google_service_account_iam_member" "operator_act_as" {
  for_each = {
    build        = google_service_account.workload["build"].name
    api_stage    = google_service_account.workload["api-stage"].name
    worker_stage = google_service_account.workload["worker-stage"].name
    api_prod     = google_service_account.workload["api-prod"].name
    worker_prod  = google_service_account.workload["worker-prod"].name
    migrator     = google_service_account.workload["migrator"].name
  }
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}
resource "google_artifact_registry_repository_iam_member" "build_writer" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.app.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.workload["build"].email}"
}
resource "google_project_iam_member" "build_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.workload["build"].email}"
}
