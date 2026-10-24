variable "project_id" {
  description = "Dedicated disposable GCP project ID."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid GCP project ID."
  }
}

variable "region" {
  description = "Single region for all regional Lab resources."
  type        = string
  default     = "asia-southeast1"
}

variable "zone" {
  description = "Zone for the branch probe VM; must belong to region."
  type        = string
  default     = "asia-southeast1-a"
  validation {
    condition     = startswith(var.zone, format("%s-", var.region))
    error_message = "zone must belong to the selected region."
  }
}

variable "operator_email" {
  description = "Google user who will administer the IAP-only probe VM."
  type        = string
  validation {
    condition     = can(regex("^[^ @]+@[^ @]+[.][^ @]+$", var.operator_email))
    error_message = "operator_email must be a valid email address."
  }
}

variable "container_image" {
  description = "Cloud Run image; public hello image is only the bootstrap revision."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "vpn_shared_secret_a" {
  description = "Write-only shared secret for HA VPN tunnel pair A."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.vpn_shared_secret_a) >= 8 && length(var.vpn_shared_secret_a) <= 64
    error_message = "VPN shared secrets must be 8-64 characters."
  }
}

variable "vpn_shared_secret_b" {
  description = "Write-only shared secret for HA VPN tunnel pair B."
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.vpn_shared_secret_b) >= 8 && length(var.vpn_shared_secret_b) <= 64
    error_message = "VPN shared secrets must be 8-64 characters."
  }
}

variable "vpn_secret_version" {
  description = "Increase this number when deliberately rotating write-only tunnel secrets."
  type        = string
  default     = "1"
  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.vpn_secret_version))
    error_message = "vpn_secret_version must be a positive integer encoded as a string."
  }
}

variable "simulate_tunnel_a_failure" {
  description = "Controlled fault: remove only tunnel pair A from both gateways."
  type        = bool
  default     = false
}

variable "authorize_branch_dns" {
  description = "Whether the private lab.internal. zone is visible to the branch VPC."
  type        = bool
  default     = true
}

variable "branch_additional_cidr" {
  description = "Approved Change Request prefix; only 10.70.1.0/24 is accepted."
  type        = string
  default     = ""
  validation {
    condition     = var.branch_additional_cidr == "" || var.branch_additional_cidr == "10.70.1.0/24"
    error_message = "Only the preflight-approved Change Request range 10.70.1.0/24 is accepted."
  }
}
