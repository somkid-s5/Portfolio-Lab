variable "project_id" {
  description = "Dedicated Google Cloud project for this lab."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID."
  }
}

variable "region" {
  description = "Region used by Cloud Run, Cloud SQL, Memorystore and Artifact Registry."
  type        = string
  default     = "asia-southeast1"

  validation {
    condition     = var.region == "asia-southeast1"
    error_message = "This baseline is designed for asia-southeast1."
  }
}

variable "operator_member" {
  description = "Principal who submits the image build and invokes the protected operator service."
  type        = string

  validation {
    condition     = can(regex("^(user|group|serviceAccount):[^[:space:]]+$", var.operator_member))
    error_message = "Use a user:, group:, or serviceAccount: IAM member."
  }
}

variable "enable_workloads" {
  description = "Create Cloud Run services and the one-shot migration Job after the image and secret versions exist."
  type        = bool
  default     = false
}

variable "image_uri" {
  description = "Immutable Artifact Registry image URI pinned by sha256 digest; required when workloads are enabled."
  type        = string
  default     = ""

  validation {
    condition = (
      !var.enable_workloads ||
      can(regex(
        "^asia-southeast1-docker\\.pkg\\.dev/${var.project_id}/lab010-images/catalog@sha256:[a-f0-9]{64}$",
        var.image_uri
      ))
    )
    error_message = "When workloads are enabled, image_uri must be this project's Lab 10 catalog image pinned by sha256 digest."
  }
}

variable "redis_auth_version" {
  description = "Numeric Secret Manager version created outside Terraform; kept out of Terraform state."
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_workloads || can(regex("^[1-9][0-9]*$", var.redis_auth_version))
    error_message = "Set redis_auth_version to an existing positive numeric Secret Manager version."
  }
}

variable "redis_ca_version" {
  description = "Numeric Secret Manager version containing the pinned Memorystore server CA."
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_workloads || can(regex("^[1-9][0-9]*$", var.redis_ca_version))
    error_message = "Set redis_ca_version to an existing positive numeric Secret Manager version."
  }
}

variable "category_list_ttl_seconds" {
  description = "Change-request input for category list cache freshness; baseline is 60 seconds."
  type        = number
  default     = 60

  validation {
    condition     = var.category_list_ttl_seconds >= 1 && var.category_list_ttl_seconds <= 60
    error_message = "Category list TTL must be between 1 and 60 seconds."
  }
}

variable "allow_destroy" {
  description = "Disable deletion protection only during the reviewed cleanup task."
  type        = bool
  default     = false
}
