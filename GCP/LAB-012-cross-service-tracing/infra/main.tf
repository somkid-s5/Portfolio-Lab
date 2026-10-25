locals {
  enabled_apis = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
    "telemetry.googleapis.com",
  ])
  collector_principal = "principal://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog/subject/ns/checkout/sa/otel-collector"
}
data "google_project" "current" {
  project_id = var.project_id
}
resource "google_project_service" "api" {
  for_each           = local.enabled_apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
resource "google_compute_network" "lab" {
  project                 = var.project_id
  name                    = "lab012-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "Dedicated VPC for the cross-service tracing solution lab."
  depends_on              = [google_project_service.api]
}
resource "google_compute_subnetwork" "gke" {
  project                  = var.project_id
  name                     = "lab012-gke-subnet"
  region                   = var.region
  network                  = google_compute_network.lab.id
  ip_cidr_range            = "10.32.0.0/20"
  private_ip_google_access = true
  description              = "Private GKE nodes and Private Google Access for Google APIs."
  secondary_ip_range {
    range_name    = "lab012-pods"
    ip_cidr_range = "10.34.0.0/16"
  }
  secondary_ip_range {
    range_name    = "lab012-services"
    ip_cidr_range = "10.35.0.0/20"
  }
}
resource "google_compute_subnetwork" "gateway_proxy" {
  project       = var.project_id
  name          = "lab012-gateway-proxy"
  region        = var.region
  network       = google_compute_network.lab.id
  ip_cidr_range = "10.36.0.0/23"
  purpose       = "REGIONAL_MANAGED_PROXY"
  role          = "ACTIVE"
  description   = "Proxy-only subnet required by the regional external GKE Gateway."
}
resource "google_service_account" "node" {
  project      = var.project_id
  account_id   = "lab012-gke-node"
  display_name = "Lab 12 GKE node service account"
  description  = "Node system tasks and private Artifact Registry image pulls."
  depends_on   = [google_project_service.api]
}
resource "google_project_iam_member" "node_default_role" {
  project = var.project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = google_service_account.node.member
}
resource "google_service_account_iam_member" "operator_can_use_node" {
  service_account_id = google_service_account.node.name
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}
resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "lab012-images"
  description   = "Private images for the Lab 12 synthetic checkout services."
  format        = "DOCKER"
  labels        = { lab = "lab012" }
  depends_on    = [google_project_service.api]
}
resource "google_artifact_registry_repository_iam_member" "node_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.reader"
  member     = google_service_account.node.member
}
resource "google_service_account" "build" {
  project      = var.project_id
  account_id   = "lab012-build"
  display_name = "Lab 12 image builder"
  description  = "Builds checkout and writes only to the lab Artifact Registry repository."
  depends_on   = [google_project_service.api]
}
resource "google_artifact_registry_repository_iam_member" "build_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.build.member
}
resource "google_project_iam_member" "build_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = google_service_account.build.member
}
resource "google_service_account_iam_member" "operator_can_use_builder" {
  service_account_id = google_service_account.build.name
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}
resource "google_project_iam_member" "collector_trace_writer" {
  project = var.project_id
  role    = "roles/telemetry.tracesWriter"
  member  = local.collector_principal
}
resource "google_project_iam_member" "collector_service_usage" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = local.collector_principal
}
resource "google_compute_address" "gateway" {
  project      = var.project_id
  name         = "lab012-gateway-ip"
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
  description  = "Regional static address reserved for the Lab 12 external Gateway."
  depends_on   = [google_project_service.api]
}
resource "google_container_cluster" "checkout" {
  project             = var.project_id
  name                = "lab012-checkout"
  location            = var.region
  enable_autopilot    = true
  networking_mode     = "VPC_NATIVE"
  network             = google_compute_network.lab.id
  subnetwork          = google_compute_subnetwork.gke.id
  deletion_protection = !var.allow_destroy
  resource_labels     = { lab = "lab012" }
  logging_service     = "logging.googleapis.com/kubernetes"
  monitoring_service  = "monitoring.googleapis.com/kubernetes"
  ip_allocation_policy {
    cluster_secondary_range_name  = "lab012-pods"
    services_secondary_range_name = "lab012-services"
  }
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
  }
  control_plane_endpoints_config {
    dns_endpoint_config {
      allow_external_traffic = true
    }
    ip_endpoints_config {
      enabled = false
    }
  }
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
  release_channel {
    channel = "REGULAR"
  }
  cluster_autoscaling {
    auto_provisioning_defaults {
      service_account = google_service_account.node.email
      oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    }
  }
  depends_on = [
    google_project_service.api,
    google_project_iam_member.node_default_role,
    google_service_account_iam_member.operator_can_use_node,
    google_artifact_registry_repository_iam_member.node_reader,
  ]
}
