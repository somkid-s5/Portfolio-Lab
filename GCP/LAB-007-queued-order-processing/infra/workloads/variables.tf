variable "project_id" {
  type        = string
  description = "The same dedicated sandbox project used by infra/foundation."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID."
  }
}

variable "serving_image" {
  type        = string
  description = "Immutable Artifact Registry image reference ending in @sha256:<digest>."
  validation {
    condition = can(regex(
      "^asia-southeast1-docker[.]pkg[.]dev/${var.project_id}/lab007-images/order-queue@sha256:[a-f0-9]{64}$",
      var.serving_image
    ))
    error_message = "Use the pushed order-queue image by digest from the Lab 07 repository."
  }
}

variable "bootstrap_image" {
  type        = string
  description = "Immutable, separate bootstrap image reference ending in @sha256:<digest>."
  validation {
    condition = can(regex(
      "^asia-southeast1-docker[.]pkg[.]dev/${var.project_id}/lab007-images/bootstrap@sha256:[a-f0-9]{64}$",
      var.bootstrap_image
    ))
    error_message = "Use the pushed bootstrap image by digest from the Lab 07 repository."
  }
}

variable "secret_versions" {
  type = object({
    auth       = string
    portal     = string
    worker     = string
    dispatcher = string
    bootstrap  = string
  })
  description = "Numeric versions printed by publish_secrets.py; secret payloads never enter Terraform."
  validation {
    condition = alltrue([
      for version in values(var.secret_versions) :
      can(regex("^[1-9][0-9]{0,9}$", version))
    ])
    error_message = "Pin a numeric version for each Lab 07 Secret."
  }
}

variable "worker_max_instances" {
  type        = number
  default     = 1
  description = "Baseline worker scale; the change exercise raises this to 3 after reviewing the DB budget."
  validation {
    condition     = contains([1, 3], var.worker_max_instances)
    error_message = "Use the baseline 1 or the approved change value 3."
  }
}

variable "worker_fault_mode" {
  type        = string
  default     = "off"
  description = "Lab-only retryable 503 before any Worker database write; default off."
  validation {
    condition     = contains(["off", "retryable_503"], var.worker_fault_mode)
    error_message = "Use off or the controlled retryable_503 exercise mode."
  }
}

variable "operator_member" {
  type        = string
  default     = ""
  description = "Optional IAM member (for example user:you@example.com) allowed to pull the dead-letter inspection subscription."
  validation {
    condition     = var.operator_member == "" || can(regex("^(user|group|serviceAccount):.+$", var.operator_member))
    error_message = "Use a user:, group:, or serviceAccount: IAM member, or leave empty and grant access manually."
  }
}

variable "allow_destroy" {
  type        = bool
  default     = false
  description = "Explicitly disables deletion protections for the Cloud Run resources."
}
