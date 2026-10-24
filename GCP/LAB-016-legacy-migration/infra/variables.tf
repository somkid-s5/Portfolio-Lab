variable "project_id" {
  description = "Existing Google Cloud project ID; Terraform does not create a project."
  type = string
  validation {
    condition = length(var.project_id) >= 6 && length(var.project_id) <= 30
    error_message = "Enter the ID of an existing Google Cloud project."
  }
}
variable "region" { type = string, default = "asia-southeast1" }
variable "zone" { type = string, default = "asia-southeast1-a" }
variable "sql_tier" {
  description = "Review regional availability and cost before apply."
  type = string
  default = "db-custom-1-3840"
}
variable "source_machine_type" { type = string, default = "e2-small" }
