variable "project_id" {
  description = "Existing Google Cloud project ID with billing and required IAM access."
  type        = string
}

variable "region" {
  description = "Single region used for Cloud Run, Cloud SQL, VPC subnet, Artifact Registry and bucket."
  type        = string
  default     = "asia-southeast1"
}

variable "bucket_name" {
  description = "Globally unique bucket name. Use a project-scoped name and record the chosen value."
  type        = string

  validation {
    condition     = length(var.bucket_name) >= 3 && length(var.bucket_name) <= 63 && can(regex("^[a-z0-9][a-z0-9._-]*[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be 3 to 63 lowercase characters, digits, dots, underscores, or hyphens, with a lowercase letter or digit at both ends."
  }
}

variable "db_tier" {
  description = "Cloud SQL machine tier. This lab creates paid resources; inspect current pricing before apply."
  type        = string
  default     = "db-custom-1-3840"
}

variable "backup_start_time" {
  description = "Daily automated backup window in UTC, HH:MM."
  type        = string
  default     = "03:00"

  validation {
    condition     = can(regex("^([01][0-9]|2[0-3]):[0-5][0-9]$", var.backup_start_time))
    error_message = "backup_start_time must use 24-hour HH:MM UTC."
  }
}
