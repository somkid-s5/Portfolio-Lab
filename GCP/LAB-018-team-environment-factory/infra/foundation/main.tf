terraform {
  required_version = ">= 1.9.8, < 2.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 7.29.0"
    }
  }
}

provider "google" {
  project = var.foundation_project_id
  region  = "asia-southeast1"
}

variable "foundation_project_id" {
  type        = string
  description = "Existing Foundation project for state and centralized logs."
}
variable "state_bucket_name" {
  type        = string
  description = "Globally unique bucket created before backend initialization."
}
variable "state_bucket_location" {
  type    = string
  default = "ASIA"
}
variable "log_locations" {
  type        = set(string)
  description = "Approved regional Cloud Logging locations."
  default     = ["asia-southeast1"]
}
variable "operator_member" {
  type        = string
  description = "Foundation operator principal, for example user:operator@example.com."
}
variable "platform_group" {
  type        = string
  description = "Existing platform operators group email."
}
variable "sink_writer_identities" {
  type        = set(string)
  description = "Sink identities returned by environment stacks."
  default     = []
}

locals {
  required_services = toset([
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
  ])
  sink_roles = toset(["roles/logging.logWriter", "roles/logging.bucketWriter"])
  sink_bindings = {
    for binding in setproduct(var.sink_writer_identities, local.sink_roles) :
    "${binding[0]}|${binding[1]}" => {
      member = binding[0]
      role   = binding[1]
    }
  }
}

resource "google_project_service" "required" {
  for_each           = local.required_services
  project            = var.foundation_project_id
  service            = each.value
  disable_on_destroy = false
}

# Create this bucket in the Console first, then import it into this remote state.
resource "google_storage_bucket" "tf_state" {
  project                     = var.foundation_project_id
  name                        = var.state_bucket_name
  location                    = var.state_bucket_location
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_service_account" "factory" {
  project      = var.foundation_project_id
  account_id   = "lab18-environment-factory"
  display_name = "Lab 18 Environment Factory"
}

resource "google_service_account_iam_member" "operator_impersonates_factory" {
  service_account_id = google_service_account.factory.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = var.operator_member
}

resource "google_storage_bucket_iam_member" "state_operator" {
  bucket = google_storage_bucket.tf_state.name
  role   = "roles/storage.objectAdmin"
  member = var.operator_member
}

resource "google_storage_bucket_iam_member" "state_factory" {
  bucket = google_storage_bucket.tf_state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.factory.email}"
}

resource "google_project_iam_member" "factory_quota_consumer" {
  project = var.foundation_project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.factory.email}"
}

resource "google_project_iam_member" "platform_log_view" {
  project = var.foundation_project_id
  role    = "roles/logging.viewAccessor"
  member  = "group:${var.platform_group}"
}

resource "google_logging_project_bucket_config" "central" {
  for_each       = var.log_locations
  project        = var.foundation_project_id
  location       = each.value
  bucket_id      = "lab18-central-${replace(each.value, "-", "")}"
  description    = "Regional central log bucket for Lab 18 environments."
  retention_days = 30
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_iam_member" "sink_writer" {
  for_each = local.sink_bindings
  project  = var.foundation_project_id
  role     = each.value.role
  member   = each.value.member
}

output "factory_service_account_email" {
  value       = google_service_account.factory.email
  description = "Keyless service account used by the factory."
}
output "state_bucket_name" {
  value       = google_storage_bucket.tf_state.name
  description = "Remote Terraform backend bucket."
}
output "central_log_bucket_ids" {
  value = {
    for location, bucket in google_logging_project_bucket_config.central :
    location => bucket.bucket_id
  }
}
