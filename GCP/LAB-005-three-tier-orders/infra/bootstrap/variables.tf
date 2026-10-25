variable "project_id" {
  type = string
  validation {
    condition = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use the dedicated foundation project ID."
  }
}
variable "artifact_bucket" {
  type = string
  validation {
    condition = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.artifact_bucket))
    error_message = "Use the foundation private artifact bucket."
  }
}
variable "debian_image" {
  type = string
  description = "Resolved Debian 12 image self-link/name; record it for rebuild, no moving family."
  validation {
    condition = can(regex("^projects/debian-cloud/global/images/debian-12-[a-z0-9-]+$", var.debian_image))
    error_message = "Resolve a concrete Debian 12 image and supply projects/debian-cloud/global/images/NAME."
  }
}
variable "api_sha256" {
  type = string
  validation {
    condition = can(regex("^[a-f0-9]{64}$", var.api_sha256))
    error_message = "Pin the verified API archive SHA256."
  }
}
variable "secret_versions" {
  type = object({ db = string, admin = string })
  validation {
    condition = alltrue([for value in values(var.secret_versions) : can(regex("^[1-9][0-9]{0,8}$", value))])
    error_message = "Pin numeric runtime DB and bootstrap-admin versions."
  }
}
