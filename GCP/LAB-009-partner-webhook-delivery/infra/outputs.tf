output "artifact_registry_repository" {
  description = "Private Docker repository used for the Lab 09 container image."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "image_uri_example" {
  description = "Replace the digest placeholder with the digest returned by Artifact Registry."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/partner-relay@sha256:<64-hex-digest>"
}

output "firestore_database" {
  description = "Firestore Native database used by the event and delivery ledger."
  value       = google_firestore_database.ledger.name
}

output "task_queues" {
  description = "Partner-isolated Cloud Tasks queues."
  value       = { for partner_id, queue in google_cloud_tasks_queue.partner : partner_id => queue.id }
}

output "partner_secret_names" {
  description = "Secret metadata only; secret values are added separately from Cloud Shell."
  value       = { for partner_id, secret in google_secret_manager_secret.partner : partner_id => secret.secret_id }
}

output "receipt_buckets" {
  description = "Private per-partner receipt buckets."
  value       = { for partner_id, bucket in google_storage_bucket.receipts : partner_id => bucket.name }
}

output "service_accounts" {
  description = "Runtime identities; no service account keys are created."
  value       = { for name, account in google_service_account.runtime : name => account.email }
}

output "workload_urls" {
  description = "Cloud Run URLs are null until the image is built and enable_workloads=true."
  value = {
    event_api  = try(google_cloud_run_v2_service.event_api[0].uri, null)
    worker     = try(google_cloud_run_v2_service.worker[0].uri, null)
    reconciler = try(google_cloud_run_v2_service.reconciler[0].uri, null)
    simulators = { for partner_id, service in google_cloud_run_v2_service.simulator : partner_id => service.uri }
  }
}
