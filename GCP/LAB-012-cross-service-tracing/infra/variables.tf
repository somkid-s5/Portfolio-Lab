variable "project_id" {
  description = "Disposable GCP project ID for Lab 12"
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a lowercase Google Cloud project ID (6-30 characters)."
  }
}
variable "region" {
  description = "Region for GKE, Gateway and Artifact Registry"
  type        = string
  default     = "asia-southeast1"
}
variable "operator_member" {
  description = "IAM member allowed to run Cloud Build and use the cluster"
  type        = string
  validation {
    condition     = can(regex("^(user|serviceAccount):[^[:space:]]+$", var.operator_member))
    error_message = "Use an IAM member such as user:name@example.com."
  }
}
variable "allow_destroy" {
  description = "Set true only to remove GKE deletion protection during cleanup."
  type        = bool
  default     = false
}
