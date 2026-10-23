variable "project_id" { type = string }
variable "bucket_names" {
  type = object({ incoming = string, results = string })
  validation {
    condition = var.bucket_names.incoming != var.bucket_names.results
    error_message = "Incoming and results buckets must be different."
  }
}
variable "image" {
  type = string
  validation {
    condition = can(regex("^asia-southeast1-docker[.]pkg[.]dev/[a-z0-9-]+/lab006-files/files@sha256:[a-f0-9]{64}$", var.image))
    error_message = "Use the Lab006 Artifact Registry image pinned by SHA256 digest."
  }
}
variable "auth_version" {
  type = string
  validation {
    condition = can(regex("^[1-9][0-9]*$", var.auth_version))
    error_message = "Use a numeric enabled auth Secret version, never latest."
  }
}
variable "upload_limit_mode" {
  type = string
  default = "baseline"
  validation {
    condition = contains(["baseline", "large"], var.upload_limit_mode)
    error_message = "Select baseline or large."
  }
}
variable "worker_fail_after_output_once" {
  type = bool
  default = false
}
variable "allow_destroy" {
  type = bool
  default = false
}
