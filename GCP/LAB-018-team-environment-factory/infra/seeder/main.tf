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
  region = "asia-southeast1"
}

variable "environment" {
  type        = string
  description = "Approved environment key from config/environments.json."
}
variable "folder_id" {
  type        = string
  description = "Existing team Folder numeric ID without folders/ prefix."
}
variable "billing_account_id" {
  type        = string
  description = "Existing billing account ID."
}
variable "allow_project_delete" {
  type        = bool
  description = "Keep false except during reviewed cleanup."
  default     = false
}

locals {
  profile       = jsondecode(file("${path.module}/../../config/environments.json"))
  allowed       = try(local.profile.allowed_regions, [])
  environment   = try(local.profile.environments[var.environment], {})
  project_id    = try(local.environment.project_id, "")
  project_name  = try(local.environment.project_name, "")
  region        = try(local.environment.region, "")
  labels        = merge(try(local.profile.labels, {}), try(local.environment.labels, {}))
}

resource "terraform_data" "profile_gate" {
  input = { environment = var.environment, region = local.region }
  lifecycle {
    precondition {
      condition     = contains(local.allowed, local.region) && local.project_id != ""
      error_message = "The profile is missing or its region is not approved."
    }
  }
}

resource "google_project" "environment" {
  project_id          = local.project_id
  name                = local.project_name
  folder_id           = var.folder_id
  billing_account     = var.billing_account_id
  auto_create_network = false
  labels              = local.labels
  deletion_policy     = var.allow_project_delete ? "DELETE" : "PREVENT"
  depends_on          = [terraform_data.profile_gate]
}

output "project_id" {
  value       = google_project.environment.project_id
  description = "Created environment project ID."
}
output "project_number" {
  value       = google_project.environment.number
  description = "Project number used by the budget filter."
}
output "region" {
  value       = local.region
  description = "Approved environment region."
}
