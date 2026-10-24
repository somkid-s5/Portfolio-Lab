variable "project_id" {
  description = "Dedicated Google Cloud project for this solution."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID."
  }
}

variable "region" {
  description = "Shared region for Cloud Run, Cloud Tasks, Firestore and Cloud Scheduler."
  type        = string
  default     = "asia-southeast1"

  validation {
    condition     = var.region == "asia-southeast1"
    error_message = "The Lab 09 solution is designed for asia-southeast1."
  }
}

variable "bucket_suffix" {
  description = "Short globally unique lowercase suffix for receipt buckets."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{6,10}$", var.bucket_suffix))
    error_message = "bucket_suffix must contain 6 to 10 lowercase letters or digits."
  }
}

variable "operator_member" {
  description = "Principal that runs the operations guide, for example user:operator@example.com."
  type        = string

  validation {
    condition     = can(regex("^(user|group|serviceAccount):[^[:space:]]+$", var.operator_member))
    error_message = "Use a user:, group:, or serviceAccount: principal."
  }
}

variable "producer_member" {
  description = "Principal allowed to submit synthetic events, usually the learner's user identity."
  type        = string

  validation {
    condition     = can(regex("^(user|group|serviceAccount):[^[:space:]]+$", var.producer_member))
    error_message = "Use a user:, group:, or serviceAccount: principal."
  }
}

variable "partners" {
  description = "Allowlisted synthetic partners. Add partner-b only at the change-request task."
  type = map(object({
    fault_mode     = string
    secret_version = string
  }))

  default = {
    partner-a = {
      fault_mode     = "transient-503-first-two"
      secret_version = "1"
    }
  }

  validation {
    condition = (
      length(var.partners) >= 1 &&
      length(var.partners) <= 2 &&
      alltrue([
        for partner_id, partner in var.partners :
        can(regex("^[a-z0-9](?:[a-z0-9-]{0,10}[a-z0-9])?$", partner_id)) &&
        contains([
          "normal",
          "transient-503-first-two",
          "permanent-400",
          "accept-then-503-on-first",
        ], partner.fault_mode) &&
        can(regex("^[1-9][0-9]*$", partner.secret_version))
      ])
    )
    error_message = "Use one or two short partner IDs, a supported fault mode and a numbered secret version."
  }
}

variable "enable_workloads" {
  description = "Create Cloud Run services and Scheduler only after the image has been pushed by digest."
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
        "^asia-southeast1-docker\\.pkg\\.dev/${var.project_id}/lab009-images/partner-relay@sha256:[a-f0-9]{64}$",
        var.image_uri
      ))
    )
    error_message = "When enable_workloads=true, image_uri must be this project's Lab 09 Artifact Registry image pinned by sha256 digest."
  }
}

variable "pause_scheduler" {
  description = "Keep periodic reconciliation paused until the first manual smoke test is verified."
  type        = bool
  default     = true
}

variable "allow_destroy" {
  description = "Explicitly disable Terraform deletion protection only during the reviewed cleanup task."
  type        = bool
  default     = false
}
