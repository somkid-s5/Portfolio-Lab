variable "project_id" {
  type = string
  description = "Existing dedicated sandbox project with billing enabled."
  validation {
    condition = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a Google Cloud project ID, not its display name or number."
  }
}
variable "region" {
  type = string
  default = "asia-southeast1"
}
variable "allow_destroy" {
  type = bool
  default = false
  description = "Set true and apply only during deliberate cleanup, then destroy."
}
