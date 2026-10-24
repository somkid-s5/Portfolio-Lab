variable "project_id" {
  description = "Disposable Google Cloud project ID used only for this lab."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a lowercase Google Cloud project ID (6-30 characters)."
  }
}
variable "region" {
  description = "Region for the Batch workers, subnet, buckets and Artifact Registry."
  type        = string
  default     = "asia-southeast1"
}
variable "operator_member" {
  description = "IAM principal that submits jobs, reads evidence and publishes completion manifests."
  type        = string
  validation {
    condition     = can(regex("^(user|serviceAccount):[^[:space:]]+$", var.operator_member))
    error_message = "Use an IAM member such as user:engineer@example.com."
  }
}
variable "bucket_prefix" {
  description = "Globally unique lowercase prefix; Terraform appends -input, -attempt and -published."
  type        = string
  validation {
    condition     = length(var.bucket_prefix) >= 3 && length(var.bucket_prefix) <= 53 && can(regex("^[a-z0-9][a-z0-9-]*[a-z0-9]$", var.bucket_prefix)) && !startswith(var.bucket_prefix, "goog") && !startswith(var.bucket_prefix, "google")
    error_message = "bucket_prefix must be 3-53 lowercase letters/digits/hyphens, not begin with goog/google, and not end with a hyphen."
  }
}
