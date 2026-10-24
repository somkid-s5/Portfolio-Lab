variable "project_id" {
  type = string
  validation {
    condition = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use the sandbox project ID."
  }
}
variable "bucket_names" {
  type = object({ incoming = string, results = string })
  validation {
    condition = var.bucket_names.incoming != var.bucket_names.results && alltrue([for name in values(var.bucket_names) : can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", name))])
    error_message = "Choose two different new globally unique bucket names."
  }
}
variable "portal_origin" {
  type = string
  default = ""
  validation {
    condition = var.portal_origin == "" || can(regex("^https://[a-z0-9-]+[.][a-z0-9.-]*run[.]app$", var.portal_origin))
    error_message = "Use the exact HTTPS Cloud Run portal origin without trailing slash."
  }
}
variable "allow_destroy" {
  type = bool
  default = false
}
