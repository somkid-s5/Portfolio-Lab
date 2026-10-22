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
variable "release_sha256" {
  type = map(string)
  validation {
    condition = toset(keys(var.release_sha256)) == toset(["web", "api"]) && alltrue([for value in values(var.release_sha256) : can(regex("^[a-f0-9]{64}$", value))])
    error_message = "Provide exactly web/api SHA256 values from the verified release manifest."
  }
}
variable "secret_versions" {
  type = object({ db = string, auth = string })
  validation {
    condition = alltrue([for value in values(var.secret_versions) : can(regex("^[1-9][0-9]{0,8}$", value))])
    error_message = "Pin numeric Secret versions, never latest."
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
variable "domain" {
  type = string
  validation {
    condition = can(regex("^[a-z0-9][a-z0-9.-]*[.][a-z]{2,}$", var.domain))
    error_message = "Supply a DNS hostname you control, without scheme/path."
  }
}
variable "api_replicas" {
  type = number
  default = 2
  validation {
    condition = contains([2, 4], var.api_replicas)
    error_message = "Lab budget allows API baseline2 or change4."
  }
}
