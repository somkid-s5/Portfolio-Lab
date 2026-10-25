variable "project_id" {
  type = string
  description = "Dedicated sandbox project; no production/shared VPC."
  validation {
    condition = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid project ID."
  }
}
variable "artifact_bucket" {
  type = string
  description = "Globally unique private release bucket name."
  validation {
    condition = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.artifact_bucket))
    error_message = "Use a 3–63 character lowercase bucket name without dots."
  }
}
variable "allow_destroy" {
  type = bool
  default = false
  description = "Explicit cleanup gate; never changes backups or deletes resources by itself."
}
