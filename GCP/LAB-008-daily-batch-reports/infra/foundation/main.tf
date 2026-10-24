locals {
  apis = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "storage.googleapis.com",
  ])
  bucket_names = {
    source = "lab008-s-${var.project_id}-${var.bucket_suffix}"
    report = "lab008-r-${var.project_id}-${var.bucket_suffix}"
  }
  service_accounts = toset(["coordinator", "worker", "scheduler"])
}

resource "google_project_service" "api" {
  for_each           = local.apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "source" {
  project                     = var.project_id
  name                        = local.bucket_names.source
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels = {
    lab       = "lab008"
    component = "source"
  }
  versioning {
    enabled = true
  }
  depends_on = [google_project_service.api]
}

resource "google_storage_bucket" "report" {
  project                     = var.project_id
  name                        = local.bucket_names.report
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels = {
    lab       = "lab008"
    component = "reports"
  }
  versioning {
    enabled = true
  }
  depends_on = [google_project_service.api]
}

resource "google_firestore_database" "ledger" {
  project     = var.project_id
  name        = "lab008-reports"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.api]
}

resource "google_pubsub_topic" "report_ready" {
  project = var.project_id
  name    = "lab008-report-ready"
  labels  = { lab = "lab008" }
  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
  depends_on = [google_project_service.api]
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "lab008-images"
  description   = "Private container images for the Daily Sales Close solution."
  format        = "DOCKER"
  labels        = { lab = "lab008" }
  depends_on    = [google_project_service.api]
}

resource "google_service_account" "runtime" {
  for_each     = local.service_accounts
  project      = var.project_id
  account_id   = "lab008-${each.value}"
  display_name = "Lab 08 ${each.value} workload identity"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_member" "firestore_runtime" {
  for_each = {
    coordinator = "roles/datastore.viewer"
    worker      = "roles/datastore.user"
  }
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime[each.key].email}"
}

resource "google_storage_bucket_iam_member" "source_reader" {
  bucket = google_storage_bucket.source.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_storage_bucket_iam_member" "report_worker" {
  for_each = toset(["roles/storage.objectViewer", "roles/storage.objectCreator"])
  bucket   = google_storage_bucket.report.name
  role     = each.value
  member   = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_storage_bucket_iam_member" "report_coordinator" {
  bucket = google_storage_bucket.report.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime["coordinator"].email}"
}

resource "google_pubsub_topic_iam_member" "worker_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.report_ready.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_artifact_registry_repository_iam_member" "image_publisher" {
  count      = var.artifact_publisher_member == "" ? 0 : 1
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.writer"
  member     = var.artifact_publisher_member
}
