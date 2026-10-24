output "database" { value = google_firestore_database.jobs.name }
output "incoming_bucket" { value = google_storage_bucket.files["incoming"].name }
output "results_bucket" { value = google_storage_bucket.files["results"].name }
output "service_accounts" {
  value = { for name, identity in google_service_account.identity : name => identity.email }
}
output "image_repository" {
  value = "asia-southeast1-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
output "auth_secret" { value = google_secret_manager_secret.auth.secret_id }
