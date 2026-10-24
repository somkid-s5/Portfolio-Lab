variable "project_id" {
  description = "Dedicated Google Cloud project ID used only for this solution lab."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID, not a project display name or number."
  }
}

variable "region" {
  description = "Single region used by the VPC, GKE cluster, Gateway, and Artifact Registry."
  type        = string
  default     = "asia-southeast1"

  validation {
    condition     = var.region == "asia-southeast1"
    error_message = "This lab's examples and regional topology are designed for asia-southeast1."
  }
}

variable "operator_member" {
  description = "Human or service identity allowed to use kubectl and submit the lab's Cloud Build."
  type        = string

  validation {
    condition     = can(regex("^(user|group|serviceAccount):[^[:space:]]+$", var.operator_member))
    error_message = "Use a fully qualified IAM member such as user:name@example.com."
  }
}

variable "allow_destroy" {
  description = "Set true only for the explicit two-step cluster deletion-protection release before cleanup."
  type        = bool
  default     = false
}
