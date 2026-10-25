terraform {
  required_version = ">= 1.9.8, < 2.0"
  backend "gcs" {}
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
  description = "Dedicated project used by the foundation root."
  type        = string
}
variable "region" {
  description = "Same region selected in foundation."
  type        = string
  default     = "asia-southeast1"
}
variable "environment" {
  description = "Stage or prod; must match the current Terraform workspace."
  type        = string
  validation {
    condition     = contains(["stage", "prod"], var.environment) && terraform.workspace == var.environment
    error_message = "Select the matching stage or prod Terraform workspace."
  }
}
variable "iap_enabled" {
  description = "Keep false for first creation, then enable IAP through Console once and reapply true."
  type        = bool
  default     = false
}
variable "migration_image_digest" {
  description = "Optional digest used only by the migration job before promoting an application release."
  type        = string
  default     = ""
  validation {
    condition     = var.migration_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.migration_image_digest))
    error_message = "migration_image_digest must be empty or an immutable sha256 digest."
  }
}
variable "image_digest" {
  description = "Immutable Artifact Registry digest from Cloud Build."
  type        = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "Use a sha256 digest, not a mutable tag."
  }
}
variable "operator_member" {
  description = "Human principal allowed into the portal and allowed to run the migration job."
  type        = string
}
variable "worker_fault_mode" {
  description = "Temporary retry-drill control; set to none after the drill."
  type        = string
  default     = "none"
  validation {
    condition     = contains(["none", "503"], var.worker_fault_mode)
    error_message = "worker_fault_mode must be none or 503."
  }
}

locals {
  labels          = { lab = "lab20", environment = var.environment, managed_by = "terraform" }
  api_name        = "lab20-${var.environment}-portal"
  worker_name     = "lab20-${var.environment}-report-worker"
  job_name        = "lab20-${var.environment}-migrate"
  bucket_name     = "lab20-${var.project_id}-${var.environment}-reports"
  topic_name      = "lab20-${var.environment}-reports"
  dlq_topic_name  = "lab20-${var.environment}-reports-dlq"
  push_name       = "lab20-${var.environment}-reports-push"
  dlq_name        = "lab20-${var.environment}-reports-dlq-pull"
  api_sa          = "lab20-api-${var.environment}@${var.project_id}.iam.gserviceaccount.com"
  worker_sa       = "lab20-worker-${var.environment}@${var.project_id}.iam.gserviceaccount.com"
  push_sa         = "lab20-push-${var.environment}@${var.project_id}.iam.gserviceaccount.com"
  migrator_sa     = "lab20-migrator@${var.project_id}.iam.gserviceaccount.com"
  api_db_user     = trimsuffix(local.api_sa, ".gserviceaccount.com")
  worker_db_user  = trimsuffix(local.worker_sa, ".gserviceaccount.com")
  db_name         = "lab20_${var.environment}"
  db_role         = "lab20_${var.environment}_runtime"
  image           = "${var.region}-docker.pkg.dev/${var.project_id}/lab20-apps/reservation-handoff@${var.image_digest}"
  migration_image = var.migration_image_digest == "" ? local.image : "${var.region}-docker.pkg.dev/${var.project_id}/lab20-apps/reservation-handoff@${var.migration_image_digest}"
  iap_audience    = "/projects/${data.google_project.current.number}/locations/${var.region}/services/${local.api_name}"
  pubsub_agent    = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
data "google_project" "current" {
  project_id = var.project_id
}
data "google_compute_network" "lab" {
  name = "lab20-vpc"
}
data "google_compute_subnetwork" "run_egress" {
  name   = "lab20-run-egress"
  region = var.region
}
data "google_sql_database_instance" "primary" {
  name = "lab20-postgres"
}

resource "google_sql_user" "api" {
  project  = var.project_id
  name     = local.api_db_user
  instance = data.google_sql_database_instance.primary.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}
resource "google_sql_user" "worker" {
  project  = var.project_id
  name     = local.worker_db_user
  instance = data.google_sql_database_instance.primary.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_pubsub_topic" "reports" {
  name                       = local.topic_name
  message_retention_duration = "86400s"
  labels                     = local.labels
}
resource "google_pubsub_topic" "dead_letter" {
  name                       = local.dlq_topic_name
  message_retention_duration = "604800s"
  labels                     = local.labels
}
resource "google_pubsub_subscription" "dead_letter_reader" {
  name                       = local.dlq_name
  topic                      = google_pubsub_topic.dead_letter.id
  message_retention_duration = "604800s"
  retain_acked_messages      = false
  ack_deadline_seconds       = 30
  labels                     = local.labels
}

resource "google_storage_bucket" "reports" {
  name                        = local.bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels
  versioning { enabled = true }
  lifecycle_rule {
    action { type = "Delete" }
    condition {
      age        = 14
      with_state = "ARCHIVED"
    }
  }
}

resource "google_cloud_run_v2_service" "api" {
  provider             = google-beta
  name                 = local.api_name
  location             = var.region
  project              = var.project_id
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = false
  iap_enabled          = var.iap_enabled
  deletion_protection  = false
  labels               = local.labels
  template {
    service_account                  = local.api_sa
    max_instance_request_concurrency = 10
    timeout                          = "30s"
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = local.image
      ports { container_port = 8080 }
      resources { limits = { cpu = "1", memory = "512Mi" } }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "INSTANCE_CONNECTION_NAME"
        value = data.google_sql_database_instance.primary.connection_name
      }
      env {
        name  = "DB_NAME"
        value = local.db_name
      }
      env {
        name  = "DB_IAM_USER"
        value = local.api_db_user
      }
      env {
        name  = "REPORT_BUCKET"
        value = google_storage_bucket.reports.name
      }
      env {
        name  = "REPORT_TOPIC"
        value = google_pubsub_topic.reports.name
      }
      env {
        name  = "IAP_AUDIENCE"
        value = local.iap_audience
      }
    }
    vpc_access {
      network_interfaces {
        network    = data.google_compute_network.lab.id
        subnetwork = data.google_compute_subnetwork.run_egress.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
  }
  depends_on = [google_sql_user.api]
}

resource "google_cloud_run_v2_service" "worker" {
  name                 = local.worker_name
  location             = var.region
  project              = var.project_id
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = false
  deletion_protection  = false
  labels               = local.labels
  template {
    service_account                  = local.worker_sa
    max_instance_request_concurrency = 1
    timeout                          = "60s"
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
    containers {
      image   = local.image
      command = ["gunicorn"]
      args    = ["--bind", ":8080", "--workers", "1", "--threads", "2", "--timeout", "55", "app.worker:app"]
      ports { container_port = 8080 }
      resources { limits = { cpu = "1", memory = "512Mi" } }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "INSTANCE_CONNECTION_NAME"
        value = data.google_sql_database_instance.primary.connection_name
      }
      env {
        name  = "DB_NAME"
        value = local.db_name
      }
      env {
        name  = "DB_IAM_USER"
        value = local.worker_db_user
      }
      env {
        name  = "REPORT_BUCKET"
        value = google_storage_bucket.reports.name
      }
      env {
        name  = "WORKER_FAULT_MODE"
        value = var.worker_fault_mode
      }
    }
    vpc_access {
      network_interfaces {
        network    = data.google_compute_network.lab.id
        subnetwork = data.google_compute_subnetwork.run_egress.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
  }
  depends_on = [google_sql_user.worker]
}

resource "google_cloud_run_v2_job" "migrate" {
  name                = local.job_name
  location            = var.region
  project             = var.project_id
  deletion_protection = false
  labels              = local.labels
  template {
    task_count  = 1
    parallelism = 1
    template {
      max_retries     = 0
      timeout         = "300s"
      service_account = local.migrator_sa
      containers {
        image   = local.migration_image
        command = ["python"]
        args    = ["-m", "app.migrate"]
        env {
          name  = "ENVIRONMENT"
          value = var.environment
        }
        env {
          name  = "INSTANCE_CONNECTION_NAME"
          value = data.google_sql_database_instance.primary.connection_name
        }
        env {
          name  = "DB_NAME"
          value = local.db_name
        }
        env {
          name  = "DB_IAM_USER"
          value = trimsuffix(local.migrator_sa, ".gserviceaccount.com")
        }
        env {
          name  = "DB_API_ROLE"
          value = "lab20-${var.environment}_api"
        }
        env {
          name  = "DB_API_USER"
          value = local.api_db_user
        }
        env {
          name  = "DB_WORKER_ROLE"
          value = "lab20-${var.environment}_worker"
        }
        env {
          name  = "DB_WORKER_USER"
          value = local.worker_db_user
        }
      }
      vpc_access {
        network_interfaces {
          network    = data.google_compute_network.lab.id
          subnetwork = data.google_compute_subnetwork.run_egress.id
        }
        egress = "PRIVATE_RANGES_ONLY"
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  count    = var.iap_enabled ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-iap.iam.gserviceaccount.com"
}
resource "google_iap_web_cloud_run_service_iam_member" "operator" {
  count                  = var.iap_enabled ? 1 : 0
  project                = var.project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.api.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = var.operator_member
}
resource "google_cloud_run_v2_service_iam_member" "push_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.push_sa}"
}
resource "google_service_account_iam_member" "pubsub_token_creator" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${local.push_sa}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.pubsub_agent
}
resource "google_pubsub_topic_iam_member" "api_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.reports.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${local.api_sa}"
}
resource "google_pubsub_topic_iam_member" "dead_letter_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.dead_letter.name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent
}
# Terraform infers this grant after the source subscription exists.
resource "google_pubsub_subscription_iam_member" "dead_letter_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.reports.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}
resource "google_storage_bucket_iam_member" "api_report_reader" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${local.api_sa}"
}
resource "google_storage_bucket_iam_member" "worker_object_writer" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${local.worker_sa}"
}
resource "google_storage_bucket_iam_member" "worker_object_reader" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${local.worker_sa}"
}

resource "google_pubsub_subscription" "reports" {
  name                       = local.push_name
  topic                      = google_pubsub_topic.reports.id
  ack_deadline_seconds       = 60
  message_retention_duration = "86400s"
  retain_acked_messages      = false
  labels                     = local.labels
  push_config {
    push_endpoint = "${google_cloud_run_v2_service.worker.uri}/events/reports"
    oidc_token {
      service_account_email = local.push_sa
      audience              = google_cloud_run_v2_service.worker.uri
    }
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 5
  }
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "60s"
  }
  depends_on = [
    google_cloud_run_v2_service_iam_member.push_invoker,
    google_service_account_iam_member.pubsub_token_creator,
    google_pubsub_topic_iam_member.dead_letter_publisher
  ]
}
resource "google_cloud_run_v2_job_iam_member" "operator_migrator" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.migrate.name
  role     = "roles/run.invoker"
  member   = var.operator_member
}
