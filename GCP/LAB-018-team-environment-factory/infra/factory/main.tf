terraform {
  required_version = ">= 1.9.8, < 2.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 7.29.0"
    }
  }
}

locals {
  profile          = jsondecode(file("${path.module}/../../config/environments.json"))
  allowed          = try(local.profile.allowed_regions, [])
  environment      = try(local.profile.environments[var.environment], {})
  project_id       = try(local.environment.project_id, "")
  region           = try(local.environment.region, "")
  labels           = merge(try(local.profile.labels, {}), try(local.environment.labels, {}))
  team_group       = try(local.environment.team_group, "")
  contractor_group = try(local.environment.contractor_group, null)
  budget           = try(local.environment.budget, {})
}

provider "google" {
  project                     = local.project_id
  region                      = local.region
  impersonate_service_account = var.factory_service_account_email
  user_project_override       = true
  billing_project             = local.project_id
}

variable "environment" {
  type        = string
  description = "Approved environment profile key."
}
variable "factory_service_account_email" {
  type        = string
  description = "Keyless factory identity from Foundation."
}
variable "foundation_project_id" {
  type        = string
  description = "Project that stores the central log bucket."
}
variable "central_log_bucket_id" {
  type        = string
  description = "Approved regional bucket ID from the Foundation stack."
}
variable "billing_account_id" {
  type        = string
  description = "Billing account linked to this environment."
}
variable "image_digest" {
  type        = string
  description = "SHA-256 image digest; required when deploying Cloud Run."
  default     = ""
  validation {
    condition     = var.image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be empty or sha256 followed by 64 lowercase hexadecimal characters."
  }
}
variable "deploy_service" {
  type        = bool
  description = "Create Cloud Run only after a pushed image digest is available."
  default     = false
}
variable "allow_destroy" {
  type        = bool
  description = "Disables Cloud Run deletion protection only during reviewed cleanup."
  default     = false
}

locals {
  api_services = toset([
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "serviceusage.googleapis.com",
  ])
}

resource "terraform_data" "profile_gate" {
  input = { environment = var.environment, region = local.region }
  lifecycle {
    precondition {
      condition     = contains(local.allowed, local.region) && local.project_id != ""
      error_message = "The environment profile is missing or its region is not approved."
    }
    precondition {
      condition     = !var.deploy_service || can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
      error_message = "A pushed image digest is required before Cloud Run deployment."
    }
  }
}

data "google_project" "current" {
  project_id = local.project_id
}

resource "google_project_service" "required" {
  for_each           = local.api_services
  project            = local.project_id
  service            = each.value
  disable_on_destroy = false
  depends_on         = [terraform_data.profile_gate]
}

resource "google_service_account" "runtime" {
  project      = local.project_id
  account_id   = "status-api-runtime"
  display_name = "Lab 18 Status API runtime"
  depends_on   = [google_project_service.required]
}

resource "google_artifact_registry_repository" "status_api" {
  project       = local.project_id
  location      = local.region
  repository_id = "lab18-status-api"
  description   = "Container images for the Lab 18 Status API."
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.required]
}

resource "google_artifact_registry_repository_iam_member" "team_push" {
  project    = local.project_id
  location   = google_artifact_registry_repository.status_api.location
  repository = google_artifact_registry_repository.status_api.name
  role       = "roles/artifactregistry.writer"
  member     = "group:${local.team_group}"
}

resource "google_project_iam_member" "team_deploy" {
  project = local.project_id
  role    = "roles/run.developer"
  member  = "group:${local.team_group}"
}

resource "google_service_account_iam_member" "factory_uses_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.factory_service_account_email}"
}

resource "google_service_account_iam_member" "team_uses_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "group:${local.team_group}"
}

resource "google_monitoring_notification_channel" "budget_email" {
  project      = local.project_id
  display_name = "Lab 18 ${var.environment} budget email"
  type         = "email"
  labels = {
    email_address = local.budget.notification_email
  }
  depends_on = [google_project_service.required]
}

resource "google_billing_budget" "environment" {
  billing_account = var.billing_account_id
  display_name    = "Lab 18 ${var.environment} alert-only budget"
  budget_filter {
    projects = ["projects/${data.google_project.current.number}"]
  }
  amount {
    specified_amount {
      currency_code = local.budget.currency
      units         = local.budget.units
    }
  }
  dynamic "threshold_rules" {
    for_each = toset(local.budget.thresholds)
    content {
      threshold_percent = threshold_rules.value
    }
  }
  all_updates_rule {
    disable_default_iam_recipients   = true
    monitoring_notification_channels = [google_monitoring_notification_channel.budget_email.name]
  }
  depends_on = [google_project_service.required]
}

resource "google_logging_project_sink" "status_api" {
  project                = local.project_id
  name                   = "lab18-${var.environment}-status-api"
  description            = "Route only Lab 18 Status API logs to the approved regional Foundation bucket."
  destination            = "logging.googleapis.com/projects/${var.foundation_project_id}/locations/${local.region}/buckets/${var.central_log_bucket_id}"
  filter                 = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"status-api\" AND logName:\"run.googleapis.com%2Fstdout\""
  unique_writer_identity = true
  depends_on             = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "status_api" {
  count                = var.deploy_service ? 1 : 0
  project              = local.project_id
  name                 = "status-api"
  location             = local.region
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = false
  deletion_protection  = !var.allow_destroy
  labels               = local.labels
  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "15s"
    max_instance_request_concurrency = 40
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = "${google_artifact_registry_repository.status_api.registry_uri}/status-api@${var.image_digest}"
      ports {
        container_port = 8080
      }
      env {
        name  = "PORT"
        value = "8080"
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "APP_VERSION"
        value = substr(var.image_digest, 7, 12)
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
      }
    }
  }
  depends_on = [
    google_project_service.required,
    google_service_account_iam_member.factory_uses_runtime,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "team_invoker" {
  count    = var.deploy_service ? 1 : 0
  project  = local.project_id
  location = local.region
  name     = google_cloud_run_v2_service.status_api[0].name
  role     = "roles/run.invoker"
  member   = "group:${local.team_group}"
}

resource "google_cloud_run_v2_service_iam_member" "contractor_viewer" {
  count    = var.deploy_service && local.contractor_group != null ? 1 : 0
  project  = local.project_id
  location = local.region
  name     = google_cloud_run_v2_service.status_api[0].name
  role     = "roles/run.viewer"
  member   = "group:${local.contractor_group}"
}

output "project_id" {
  value       = local.project_id
  description = "Environment project ID selected by the approved profile."
}
output "artifact_repository_uri" {
  value       = "${google_artifact_registry_repository.status_api.registry_uri}/status-api"
  description = "Repository URI for developer image pushes."
}
output "sink_writer_identity" {
  value       = google_logging_project_sink.status_api.writer_identity
  description = "Grant this identity the two Logging writer roles in Foundation."
}
output "service_url" {
  value       = try(google_cloud_run_v2_service.status_api[0].uri, null)
  description = "Private Cloud Run URL; null until deployment is enabled."
}
output "runtime_service_account" {
  value       = google_service_account.runtime.email
  description = "Keyless runtime identity with no application permissions."
}
