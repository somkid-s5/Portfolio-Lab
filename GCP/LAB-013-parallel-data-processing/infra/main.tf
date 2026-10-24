locals {
  enabled_apis = toset([
    "artifactregistry.googleapis.com",
    "batch.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
  ])
}
resource "google_project_service" "api" {
  for_each                   = local.enabled_apis
  project                    = var.project_id
  service                    = each.value
  disable_dependent_services = false
  disable_on_destroy         = false
}
resource "google_compute_network" "lab" {
  project                 = var.project_id
  name                    = "lab013-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "Dedicated private worker network for the Lab 13 Cloud Batch solution."
  depends_on              = [google_project_service.api]
}
resource "google_compute_subnetwork" "workers" {
  project                  = var.project_id
  name                     = "lab013-workers"
  region                   = var.region
  network                  = google_compute_network.lab.id
  ip_cidr_range            = "10.43.0.0/20"
  private_ip_google_access = true
  description              = "Batch worker subnet with Private Google Access and no public VM addresses."
}
resource "google_artifact_registry_repository" "worker" {
  project       = var.project_id
  location      = var.region
  repository_id = "lab013-images"
  description   = "Private container images for the synthetic parallel data-processing lab."
  format        = "DOCKER"
  labels        = { lab = "lab013" }
  depends_on    = [google_project_service.api]
}
resource "google_service_account" "build" {
  project      = var.project_id
  account_id   = "lab013-build"
  display_name = "Lab 13 image builder"
  description  = "Builds the worker image and writes to the Lab 13 Artifact Registry repository."
  depends_on   = [google_project_service.api]
}
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "lab013-runtime"
  display_name = "Lab 13 Batch worker"
  description  = "Reads only the input bucket and creates per-attempt output objects."
  depends_on   = [google_project_service.api]
}
resource "google_project_iam_member" "operator_build_editor" {
  project    = var.project_id
  role       = "roles/cloudbuild.builds.editor"
  member     = var.operator_member
  depends_on = [google_project_service.api]
}
resource "google_project_iam_member" "operator_service_usage_consumer" {
  project    = var.project_id
  role       = "roles/serviceusage.serviceUsageConsumer"
  member     = var.operator_member
  depends_on = [google_project_service.api]
}
resource "google_project_iam_member" "operator_batch_editor" {
  project    = var.project_id
  role       = "roles/batch.jobsEditor"
  member     = var.operator_member
  depends_on = [google_project_service.api]
}
resource "google_project_iam_member" "operator_network_viewer" {
  project    = var.project_id
  role       = "roles/compute.networkViewer"
  member     = var.operator_member
  depends_on = [google_project_service.api]
}
resource "google_project_iam_member" "operator_logging_viewer" {
  project    = var.project_id
  role       = "roles/logging.viewer"
  member     = var.operator_member
  depends_on = [google_project_service.api]
}
resource "google_service_account_iam_member" "operator_can_use_build" {
  service_account_id = google_service_account.build.name
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}
resource "google_service_account_iam_member" "operator_can_use_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}
resource "google_project_iam_member" "build_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = google_service_account.build.member
}
resource "google_artifact_registry_repository_iam_member" "build_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.worker.location
  repository = google_artifact_registry_repository.worker.repository_id
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.build.member
}
resource "google_project_iam_member" "runtime_batch_agent_reporter" {
  project = var.project_id
  role    = "roles/batch.agentReporter"
  member  = google_service_account.runtime.member
}
resource "google_project_iam_member" "runtime_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = google_service_account.runtime.member
}
resource "google_artifact_registry_repository_iam_member" "runtime_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.worker.location
  repository = google_artifact_registry_repository.worker.repository_id
  role       = "roles/artifactregistry.reader"
  member     = google_service_account.runtime.member
}
resource "google_storage_bucket" "input" {
  project                     = var.project_id
  name                        = "${var.bucket_prefix}-input"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  soft_delete_policy {
    retention_duration_seconds = 0
  }
  labels                      = { lab = "lab013", purpose = "input" }
  depends_on                  = [google_project_service.api]
}
resource "google_storage_bucket" "attempt" {
  project                     = var.project_id
  name                        = "${var.bucket_prefix}-attempt"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  soft_delete_policy {
    retention_duration_seconds = 0
  }
  labels                      = { lab = "lab013", purpose = "attempt" }
  depends_on                  = [google_project_service.api]
}
resource "google_storage_bucket" "published" {
  project                     = var.project_id
  name                        = "${var.bucket_prefix}-published"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  soft_delete_policy {
    retention_duration_seconds = 0
  }
  labels                      = { lab = "lab013", purpose = "published" }
  depends_on                  = [google_project_service.api]
}
resource "google_storage_bucket_iam_member" "operator_input_viewer" {
  bucket = google_storage_bucket.input.name
  role   = "roles/storage.objectViewer"
  member = var.operator_member
}
resource "google_storage_bucket_iam_member" "operator_input_creator" {
  bucket = google_storage_bucket.input.name
  role   = "roles/storage.objectCreator"
  member = var.operator_member
}
resource "google_storage_bucket_iam_member" "runtime_input_viewer" {
  bucket = google_storage_bucket.input.name
  role   = "roles/storage.objectViewer"
  member = google_service_account.runtime.member
}
resource "google_storage_bucket_iam_member" "operator_attempt_viewer" {
  bucket = google_storage_bucket.attempt.name
  role   = "roles/storage.objectViewer"
  member = var.operator_member
}
resource "google_storage_bucket_iam_member" "runtime_attempt_creator" {
  bucket = google_storage_bucket.attempt.name
  role   = "roles/storage.objectCreator"
  member = google_service_account.runtime.member
}
resource "google_storage_bucket_iam_member" "operator_published_viewer" {
  bucket = google_storage_bucket.published.name
  role   = "roles/storage.objectViewer"
  member = var.operator_member
}
resource "google_storage_bucket_iam_member" "operator_published_creator" {
  bucket = google_storage_bucket.published.name
  role   = "roles/storage.objectCreator"
  member = var.operator_member
}
