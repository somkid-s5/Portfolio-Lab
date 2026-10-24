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
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
  ])

  workload_secret_access = {
    api_token = {
      secret_id = "api-bearer-token"
      principal = "principal://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog/subject/ns/quote-platform/sa/quote-api"
    }
    quote_rules = {
      secret_id = "quote-rules"
      principal = "principal://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog/subject/ns/quote-platform/sa/quote-worker"
    }
  }
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
  name                    = "lab011-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "Dedicated VPC for the GKE Quote Engine solution lab."
  depends_on              = [google_project_service.api]
}

resource "google_compute_subnetwork" "gke" {
  project                  = var.project_id
  name                     = "lab011-gke-subnet"
  region                   = var.region
  network                  = google_compute_network.lab.id
  ip_cidr_range            = "10.22.0.0/20"
  private_ip_google_access = true
  description              = "Private GKE nodes; Google API access uses Private Google Access."

  secondary_ip_range {
    range_name    = "lab011-pods"
    ip_cidr_range = "10.20.0.0/16"
  }

  secondary_ip_range {
    range_name    = "lab011-services"
    ip_cidr_range = "10.21.0.0/20"
  }
}

resource "google_compute_subnetwork" "gateway_proxy" {
  project       = var.project_id
  name          = "lab011-gateway-proxy"
  region        = var.region
  network       = google_compute_network.lab.id
  ip_cidr_range = "10.23.0.0/23"
  purpose       = "REGIONAL_MANAGED_PROXY"
  role          = "ACTIVE"
  description   = "Regional managed proxy-only subnet required by the regional external Gateway."
}

resource "google_service_account" "node" {
  project      = var.project_id
  account_id   = "lab011-gke-node"
  display_name = "Lab 11 GKE node service account"
  description  = "Node system tasks and private Artifact Registry image pulls only."
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
  repository_id = "lab011-images"
  description   = "Private container images for the GKE Quote Engine solution lab."
  format        = "DOCKER"
  labels        = { lab = "lab011" }
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
  account_id   = "quote-build"
  display_name = "Lab 11 image builder"
  description  = "Builds the Quote Engine image and writes only to the lab Artifact Registry repository."
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

resource "google_project_iam_member" "operator_container_developer" {
  project = var.project_id
  role    = "roles/container.developer"
  member  = var.operator_member
}

resource "google_project_iam_member" "operator_build_editor" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.editor"
  member  = var.operator_member
}

resource "google_service_account_iam_member" "operator_can_use_builder" {
  service_account_id = google_service_account.build.name
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}

resource "google_secret_manager_secret" "api_token" {
  project   = var.project_id
  secret_id = "api-bearer-token"

  replication {
    auto {}
  }

  labels = {
    lab       = "lab011"
    component = "api-token"
  }

  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret" "quote_rules" {
  project   = var.project_id
  secret_id = "quote-rules"

  replication {
    auto {}
  }

  labels = {
    lab       = "lab011"
    component = "quote-rules"
  }

  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_iam_member" "workload" {
  for_each  = local.workload_secret_access
  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.principal

  depends_on = [
    google_container_cluster.quote,
    google_secret_manager_secret.api_token,
    google_secret_manager_secret.quote_rules,
  ]
}

resource "google_compute_address" "gateway" {
  project      = var.project_id
  name         = "lab011-gateway-ip"
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "STANDARD"
  description  = "Regional Standard-tier frontend for the Lab 11 external GKE Gateway."
  depends_on   = [google_project_service.api]
}

resource "google_container_cluster" "quote" {
  project             = var.project_id
  name                = "lab011-quote-engine"
  location            = var.region
  enable_autopilot    = true
  networking_mode     = "VPC_NATIVE"
  network             = google_compute_network.lab.id
  subnetwork          = google_compute_subnetwork.gke.id
  deletion_protection = !var.allow_destroy
  resource_labels     = { lab = "lab011" }
  logging_service     = "logging.googleapis.com/kubernetes"
  monitoring_service  = "monitoring.googleapis.com/kubernetes"

  ip_allocation_policy {
    cluster_secondary_range_name  = "lab011-pods"
    services_secondary_range_name = "lab011-services"
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
