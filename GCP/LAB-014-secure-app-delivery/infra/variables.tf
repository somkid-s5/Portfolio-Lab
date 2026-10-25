variable "project_id" {
  description = "Dedicated disposable Google Cloud project for Lab 14."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Use a valid Google Cloud project ID for a dedicated lab project."
  }
}
variable "region" {
  description = "Region used for Cloud Run, Artifact Registry, Cloud Build and Cloud Deploy."
  type        = string
  default     = "asia-southeast1"
}
variable "cloudbuild_connection_id" {
  description = "Optional full resource name of the GitHub Cloud Build v2 connection created manually in the Console."
  type        = string
  default     = ""
  validation {
    condition = var.cloudbuild_connection_id == "" || startswith(
      var.cloudbuild_connection_id,
      format("projects/%s/locations/%s/connections/", var.project_id, var.region)
    )
    error_message = "The connection ID must belong to this project and region."
  }
}
variable "github_repository_uri" {
  description = "HTTPS clone URL for the source repository."
  type        = string
  default     = "https://github.com/somkid-s5/Portfolio-Lab.git"
}
variable "approver_principal" {
  description = "Optional human user or group principal that may approve Cloud Deploy production rollouts."
  type        = string
  default     = ""
  validation {
    condition     = var.approver_principal == "" || can(regex("^(user|group):.+$", var.approver_principal))
    error_message = "Use a human user: or group: IAM principal; never bind the GitHub release service account as approver."
  }
}
variable "manage_project_binary_authorization_policy" {
  description = "Opt in only after confirming this dedicated project has no existing Binary Authorization policy. This policy is project-wide."
  type        = bool
  default     = false
}
