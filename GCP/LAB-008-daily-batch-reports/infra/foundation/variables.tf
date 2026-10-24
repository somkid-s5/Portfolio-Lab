variable "project_id" {
  description = "Dedicated Google Cloud project for this lab."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID."
  }
}

variable "region" {
  description = "Single region for the lab resources."
  type        = string
  default     = "asia-southeast1"
  validation {
    condition     = var.region == "asia-southeast1"
    error_message = "This solution's examples and diagrams are pinned to asia-southeast1."
  }
}

variable "bucket_suffix" {
  description = "Short globally unique suffix; use lowercase letters, digits, and hyphens only."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{2,15}$", var.bucket_suffix))
    error_message = "bucket_suffix must be 3-16 lowercase letters, digits, or hyphens."
  }
}

variable "artifact_publisher_member" {
  description = "Optional principal allowed to push the container image, e.g. user:operator@example.com."
  type        = string
  default     = ""
}

variable "allow_destroy" {
  description = "Set true only during an intentional teardown after reviewing the Terraform plan."
  type        = bool
  default     = false
}
