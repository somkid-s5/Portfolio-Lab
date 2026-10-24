locals {
  region = "asia-southeast1"
  apis = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com"
  ])
  secrets = {
    auth       = "lab007-auth"
    portal     = "lab007-db-portal"
    worker     = "lab007-db-worker"
    dispatcher = "lab007-db-dispatcher"
    bootstrap  = "lab007-db-bootstrap"
  }
  accounts = {
    portal     = "lab007-portal"
    worker     = "lab007-worker"
    dispatcher = "lab007-dispatcher"
    bootstrap  = "lab007-bootstrap"
    scheduler  = "lab007-scheduler"
  }
  secret_access = {
    portal_auth        = { account = "portal", secret = "auth" }
    portal_db          = { account = "portal", secret = "portal" }
    worker_db          = { account = "worker", secret = "worker" }
    dispatcher_db      = { account = "dispatcher", secret = "dispatcher" }
    bootstrap_admin    = { account = "bootstrap", secret = "bootstrap" }
    bootstrap_portal   = { account = "bootstrap", secret = "portal" }
    bootstrap_worker   = { account = "bootstrap", secret = "worker" }
    bootstrap_dispatch = { account = "bootstrap", secret = "dispatcher" }
  }
}

resource "google_project_service" "api" {
  for_each           = local.apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "lab007" {
  project                 = var.project_id
  name                    = "lab007-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.api]
}

resource "google_compute_subnetwork" "run" {
  project                  = var.project_id
  name                     = "lab007-run"
  region                   = local.region
  network                  = google_compute_network.lab007.id
  ip_cidr_range            = "10.77.10.0/26"
  private_ip_google_access = true
}

resource "google_compute_global_address" "sql_private_services" {
  project       = var.project_id
  name          = "lab007-sql-psa"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = "10.77.240.0"
  prefix_length = 24
  network       = google_compute_network.lab007.id
}

resource "google_service_networking_connection" "sql_private_services" {
  network                 = google_compute_network.lab007.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_private_services.name]
  depends_on              = [google_project_service.api]
}

resource "google_sql_database_instance" "orders" {
  project             = var.project_id
  name                = "lab007-orders"
  database_version    = "POSTGRES_16"
  region              = local.region
  deletion_protection = !var.allow_destroy
  depends_on          = [google_service_networking_connection.sql_private_services]
  settings {
    tier                        = "db-custom-2-7680"
    edition                     = "ENTERPRISE"
    availability_type           = "ZONAL"
    disk_type                   = "PD_SSD"
    disk_size                   = 20
    disk_autoresize             = false
    deletion_protection_enabled = !var.allow_destroy
    user_labels                 = { lab = "lab007", purpose = "training" }
    ip_configuration {
      ipv4_enabled       = false
      private_network    = google_compute_network.lab007.id
      allocated_ip_range = google_compute_global_address.sql_private_services.name
      ssl_mode           = "ENCRYPTED_ONLY"
    }
    database_flags {
      name  = "max_connections"
      value = "64"
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 1
      start_time                     = "18:00"
      backup_retention_settings {
        retained_backups = 2
        retention_unit   = "COUNT"
      }
    }
  }
}

resource "google_sql_database" "orders" {
  project  = var.project_id
  name     = "order_queue"
  instance = google_sql_database_instance.orders.name
}

resource "google_secret_manager_secret" "lab007" {
  for_each  = local.secrets
  project   = var.project_id
  secret_id = each.value
  location  = local.region
  replication {
    user_managed {
      replicas {
        location = local.region
      }
    }
  }
  depends_on = [google_project_service.api]
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = local.region
  repository_id = "lab007-images"
  description   = "Private container images for Lab 07"
  format        = "DOCKER"
  depends_on    = [google_project_service.api]
}

resource "google_service_account" "runtime" {
  for_each     = local.accounts
  project      = var.project_id
  account_id   = each.value
  display_name = "Lab 07 ${each.key} workload identity"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_member" "cloud_sql_client" {
  for_each = {
    for role, account in google_service_account.runtime : role => account
    if role != "scheduler"
  }
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${each.value.email}"
}

resource "google_secret_manager_secret_iam_member" "access" {
  for_each  = local.secret_access
  project   = var.project_id
  secret_id = google_secret_manager_secret.lab007[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime[each.value.account].email}"
}

resource "google_project_service_identity" "pubsub" {
  provider   = google-beta
  project    = var.project_id
  service    = "pubsub.googleapis.com"
  depends_on = [google_project_service.api]
}

resource "google_service_account_iam_member" "pubsub_token_creator" {
  service_account_id = google_service_account.runtime["worker"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_project_service_identity.pubsub.email}"
}
