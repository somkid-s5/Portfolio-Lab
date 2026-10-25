terraform {
  required_version = ">= 1.9.8, < 2.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 7.29.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "= 7.29.0"
    }
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
  description = "Existing, billing-enabled Lab project. Do not use a shared production project."
  type        = string
}

variable "region" {
  description = "Single region used by the application and database."
  type        = string
  default     = "asia-southeast1"
  validation {
    condition     = var.region == "asia-southeast1"
    error_message = "Lab 19 currently validates its example topology in asia-southeast1."
  }
}

variable "db_tier" {
  description = "Cloud SQL tier. Review current regional price before apply."
  type        = string
  default     = "db-custom-1-3840"
}

variable "operator_member" {
  description = "Principal allowed to build images and invoke the Task API, e.g. user:you@example.com."
  type        = string
  validation {
    condition     = can(regex("^(user|serviceAccount):", var.operator_member))
    error_message = "Use a complete IAM member such as user:name@example.com."
  }
}

locals {
  labels = {
    lab        = "lab19"
    managed_by = "terraform"
  }

  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "servicenetworking.googleapis.com",
    "serviceusage.googleapis.com",
    "sqladmin.googleapis.com",
    "cloudtrace.googleapis.com",
  ])

  database_accounts = {
    api      = google_service_account.api.email
    worker   = google_service_account.worker.email
    migrator = google_service_account.migrator.email
  }
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "enabled" {
  for_each                   = local.required_services
  project                    = var.project_id
  service                    = each.value
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_compute_network" "lab" {
  name                    = "lab19-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "Private egress network for the Lab 19 service observability solution."
  depends_on              = [google_project_service.enabled]
}

resource "google_compute_subnetwork" "run_egress" {
  name                     = "lab19-run-egress"
  region                   = var.region
  network                  = google_compute_network.lab.id
  ip_cidr_range            = "10.94.0.0/26"
  private_ip_google_access = true
  description              = "Direct VPC egress subnet for the Cloud Run API, worker, and migration Job."
}

resource "google_compute_global_address" "psa_range" {
  name          = "lab19-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = "10.94.16.0"
  prefix_length = 20
  network       = google_compute_network.lab.id
  description   = "Private Services Access range for Cloud SQL."
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.lab.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
  depends_on              = [google_project_service.enabled]
}

resource "google_sql_database_instance" "primary" {
  name                = "lab19-postgres"
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
      enabled = false
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.lab.id
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_service_networking_connection.private_services,
  ]
}

resource "google_sql_database" "tasks" {
  name      = "lab19"
  instance  = google_sql_database_instance.primary.name
  charset   = "UTF8"
  collation = "en_US.UTF8"
}

resource "google_pubsub_topic" "tasks" {
  name                       = "lab19-tasks"
  message_retention_duration = "86400s"
  labels                     = local.labels
  depends_on                 = [google_project_service.enabled]
}

resource "google_pubsub_topic" "dead_letter" {
  name                       = "lab19-tasks-dlq"
  message_retention_duration = "604800s"
  labels                     = local.labels
  depends_on                 = [google_project_service.enabled]
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "lab19-apps"
  description   = "Pinned application image for the Lab 19 API, worker, and migration Job."
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.enabled]
}

resource "google_service_account" "api" {
  account_id   = "lab19-api"
  display_name = "Lab 19 Task API runtime"
  description  = "Publishes tasks and reads status using a restricted database role."
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "worker" {
  account_id   = "lab19-worker"
  display_name = "Lab 19 Task Worker runtime"
  description  = "Processes tasks using a restricted database role."
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "migrator" {
  account_id   = "lab19-migrator"
  display_name = "Lab 19 one-off schema migrator"
  description  = "Runs the schema migration Job; not used by the API or worker."
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "pubsub_push" {
  account_id   = "lab19-push"
  display_name = "Lab 19 Pub/Sub push identity"
  description  = "OIDC identity used by the authenticated Pub/Sub push subscription."
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "build" {
  account_id   = "lab19-build"
  display_name = "Lab 19 container build identity"
  description  = "Cloud Build identity restricted to writing the Lab 19 Artifact Registry repository."
  depends_on   = [google_project_service.enabled]
}

resource "google_project_iam_member" "cloudsql_client" {
  for_each = local.database_accounts
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = format("serviceAccount:%s", each.value)
}

resource "google_project_iam_member" "cloudsql_instance_user" {
  for_each = local.database_accounts
  project  = var.project_id
  role     = "roles/cloudsql.instanceUser"
  member   = format("serviceAccount:%s", each.value)
}

resource "google_pubsub_topic_iam_member" "api_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.tasks.name
  role    = "roles/pubsub.publisher"
  member  = format("serviceAccount:%s", google_service_account.api.email)
}

resource "google_sql_user" "migrator" {
  project        = var.project_id
  name           = trimsuffix(google_service_account.migrator.email, ".gserviceaccount.com")
  instance       = google_sql_database_instance.primary.name
  type           = "CLOUD_IAM_SERVICE_ACCOUNT"
  database_roles = ["cloudsqlsuperuser"]
}

resource "google_service_account_iam_member" "operator_act_as_build" {
  service_account_id = google_service_account.build.name
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}

resource "google_service_account_iam_member" "operator_act_as_runtime" {
  for_each = {
    api      = google_service_account.api.name
    worker   = google_service_account.worker.name
    migrator = google_service_account.migrator.name
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
  member     = format("serviceAccount:%s", google_service_account.build.email)
}

resource "google_project_iam_member" "build_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = format("serviceAccount:%s", google_service_account.build.email)
}
