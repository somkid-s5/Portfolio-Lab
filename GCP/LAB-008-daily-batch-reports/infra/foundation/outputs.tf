output "source_bucket" {
  value       = google_storage_bucket.source.name
  description = "Private input bucket."
}

output "report_bucket" {
  value       = google_storage_bucket.report.name
  description = "Private create-only report bucket."
}

output "firestore_database" {
  value       = google_firestore_database.ledger.name
  description = "Dedicated Firestore Native database ID."
}

output "firestore_collection" {
  value       = "daily_runs"
  description = "Collection used by the application."
}

output "report_ready_topic" {
  value       = google_pubsub_topic.report_ready.id
  description = "Full Pub/Sub topic resource name."
}

output "image_repository" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
  description = "Artifact Registry repository URI for immutable image pushes."
}

output "coordinator_service_account" {
  value       = google_service_account.runtime["coordinator"].email
  description = "Cloud Run coordinator identity."
}

output "worker_service_account" {
  value       = google_service_account.runtime["worker"].email
  description = "Cloud Run Job identity."
}

output "scheduler_service_account" {
  value       = google_service_account.runtime["scheduler"].email
  description = "OIDC caller identity for Cloud Scheduler."
}
