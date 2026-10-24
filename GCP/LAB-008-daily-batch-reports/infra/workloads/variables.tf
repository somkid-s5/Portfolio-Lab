variable "project_id" {
  description = "Dedicated Google Cloud project containing Lab 08."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID."
  }
}

variable "region" {
  description = "Region shared by the workloads and Scheduler."
  type        = string
  default     = "asia-southeast1"
  validation {
    condition     = var.region == "asia-southeast1"
    error_message = "This solution's schedule and examples use asia-southeast1."
  }
}

variable "image_uri" {
  description = "Immutable Artifact Registry image reference using the pushed sha256 digest."
  type        = string
  validation {
    condition = can(regex(
      "^asia-southeast1-docker\\.pkg\\.dev/[a-z][a-z0-9-]{4,28}[a-z0-9]/lab008-images/daily-sales-close@sha256:[a-f0-9]{64}$",
      var.image_uri
    ))
    error_message = "image_uri must be the Lab 08 Artifact Registry image pinned by sha256 digest."
  }
}

variable "source_bucket" {
  description = "Foundation output: private input bucket name."
  type        = string
}

variable "report_bucket" {
  description = "Foundation output: private report bucket name."
  type        = string
}

variable "firestore_database" {
  description = "Foundation output: dedicated Firestore Native database ID."
  type        = string
}

variable "firestore_collection" {
  description = "Foundation output: application collection name."
  type        = string
  default     = "daily_runs"
}

variable "report_ready_topic" {
  description = "Foundation output: fully qualified Pub/Sub topic resource name."
  type        = string
}

variable "coordinator_service_account" {
  description = "Foundation output: coordinator runtime identity email."
  type        = string
}

variable "worker_service_account" {
  description = "Foundation output: batch worker runtime identity email."
  type        = string
}

variable "scheduler_service_account" {
  description = "Foundation output: Cloud Scheduler OIDC caller identity email."
  type        = string
}

variable "operator_member" {
  description = "Principal allowed to operate the Job and read diagnostics, e.g. user:operator@example.com."
  type        = string
  validation {
    condition     = can(regex("^(user|group|serviceAccount):[^[:space:]]+$", var.operator_member))
    error_message = "operator_member must be a user:, group:, or serviceAccount: principal."
  }
}

variable "notification_channels" {
  description = "Optional existing Monitoring notification channel resource names."
  type        = list(string)
  default     = []
}

variable "pause_schedulers" {
  description = "Keep schedule triggers paused until input, IAM and a manual smoke run are verified."
  type        = bool
  default     = true
}

variable "allow_destroy" {
  description = "Disable Cloud Run deletion protection only for an intentional reviewed teardown."
  type        = bool
  default     = false
}
