locals {
  apis = toset([
    "run.googleapis.com", "artifactregistry.googleapis.com",
    "storage.googleapis.com", "firestore.googleapis.com",
    "eventarc.googleapis.com", "pubsub.googleapis.com",
    "secretmanager.googleapis.com", "iamcredentials.googleapis.com",
    "iam.googleapis.com", "cloudresourcemanager.googleapis.com"
  ])
}
resource "google_project_service" "api" {
  for_each = local.apis
  service = each.value
  disable_on_destroy = false
}
resource "google_service_account" "identity" {
  for_each = toset(["portal", "worker", "trigger", "upload-signer", "download-signer"])
  account_id = "lab006-${each.value}"
  display_name = "Lab006 ${each.value}"
  depends_on = [google_project_service.api]
}
resource "google_firestore_database" "jobs" {
  name = "lab006-files"
  location_id = "asia-southeast1"
  type = "FIRESTORE_NATIVE"
  concurrency_mode = "PESSIMISTIC"
  app_engine_integration_mode = "DISABLED"
  delete_protection_state = var.allow_destroy ? "DELETE_PROTECTION_DISABLED" : "DELETE_PROTECTION_ENABLED"
  deletion_policy = var.allow_destroy ? "DELETE" : "PREVENT"
  depends_on = [google_project_service.api]
}
resource "google_firestore_field" "ttl" {
  for_each = toset(["jobs", "idempotency", "owner_quotas"])
  database = google_firestore_database.jobs.name
  collection = each.value
  field = "delete_after"
  ttl_config {}
  index_config {}
}
resource "google_project_iam_member" "metadata" {
  for_each = toset(["portal", "worker"])
  project = var.project_id
  role = "roles/datastore.user"
  member = "serviceAccount:${google_service_account.identity[each.value].email}"
  condition {
    title = "lab006_named_database_only"
    description = "Only the isolated Lab006 database, not the default database."
    expression = "resource.name == 'projects/${var.project_id}/databases/lab006-files'"
  }
  depends_on = [google_firestore_database.jobs]
}
resource "google_storage_bucket" "files" {
  for_each = var.bucket_names
  name = each.value
  location = "ASIA-SOUTHEAST1"
  uniform_bucket_level_access = true
  public_access_prevention = "enforced"
  force_destroy = false
  labels = { lab = "lab006", purpose = "training", tier = each.key }
  lifecycle_rule {
    action { type = "Delete" }
    condition { age = 2 }
  }
  soft_delete_policy { retention_duration_seconds = 604800 }
  dynamic "cors" {
    for_each = each.key == "incoming" && var.portal_origin != "" ? [var.portal_origin] : []
    content {
      origin = [cors.value]
      method = ["POST"]
      response_header = ["Content-Type", "x-goog-generation"]
      max_age_seconds = 300
    }
  }
  depends_on = [google_project_service.api]
}
resource "google_project_iam_custom_role" "object_read" {
  role_id = "lab006ObjectRead"
  title = "Lab006 object read only"
  permissions = ["storage.objects.get"]
  depends_on = [google_project_service.api]
}
resource "google_project_iam_custom_role" "object_create" {
  role_id = "lab006ObjectCreate"
  title = "Lab006 object create only"
  permissions = ["storage.objects.create"]
  depends_on = [google_project_service.api]
}
resource "google_project_iam_custom_role" "sign_blob" {
  role_id = "lab006SignBlob"
  title = "Lab006 signBlob only"
  permissions = ["iam.serviceAccounts.signBlob"]
  depends_on = [google_project_service.api]
}
locals {
  storage_access = {
    upload_create = { bucket = "incoming", identity = "upload-signer", role = google_project_iam_custom_role.object_create.name }
    worker_read = { bucket = "incoming", identity = "worker", role = google_project_iam_custom_role.object_read.name }
    worker_create = { bucket = "results", identity = "worker", role = google_project_iam_custom_role.object_create.name }
    worker_verify = { bucket = "results", identity = "worker", role = google_project_iam_custom_role.object_read.name }
    download_read = { bucket = "results", identity = "download-signer", role = google_project_iam_custom_role.object_read.name }
  }
}
resource "google_storage_bucket_iam_member" "access" {
  for_each = local.storage_access
  bucket = google_storage_bucket.files[each.value.bucket].name
  role = each.value.role
  member = "serviceAccount:${google_service_account.identity[each.value.identity].email}"
}
resource "google_service_account_iam_member" "portal_signing" {
  for_each = toset(["upload-signer", "download-signer"])
  service_account_id = google_service_account.identity[each.value].name
  role = google_project_iam_custom_role.sign_blob.name
  member = "serviceAccount:${google_service_account.identity["portal"].email}"
}
resource "google_secret_manager_secret" "auth" {
  secret_id = "lab006-auth"
  replication {
    auto {}
  }
  depends_on = [google_project_service.api]
}
resource "google_secret_manager_secret_iam_member" "auth" {
  secret_id = google_secret_manager_secret.auth.id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.identity["portal"].email}"
}
resource "google_artifact_registry_repository" "images" {
  location = "asia-southeast1"
  repository_id = "lab006-files"
  format = "DOCKER"
  depends_on = [google_project_service.api]
}
resource "google_project_iam_member" "event_receiver" {
  project = var.project_id
  role = "roles/eventarc.eventReceiver"
  member = "serviceAccount:${google_service_account.identity["trigger"].email}"
}
data "google_storage_project_service_account" "agent" {
  project = var.project_id
  depends_on = [google_project_service.api]
}
resource "google_project_iam_member" "storage_event_publisher" {
  project = var.project_id
  role = "roles/pubsub.publisher"
  member = "serviceAccount:${data.google_storage_project_service_account.agent.email_address}"
}
