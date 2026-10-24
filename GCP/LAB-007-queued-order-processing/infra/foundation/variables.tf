variable "project_id" {
  type        = string
  description = "Dedicated disposable sandbox project for Lab 07."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID."
  }
}

variable "allow_destroy" {
  type        = bool
  default     = false
  description = "Explicitly disables SQL and Cloud resource deletion protections when set true."
}
