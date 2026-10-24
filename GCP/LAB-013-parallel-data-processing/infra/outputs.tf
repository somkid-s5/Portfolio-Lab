output "project_id" {
  value       = var.project_id
  description = "Google Cloud project used by Lab 13."
}
output "region" {
  value       = var.region
  description = "Cloud Batch and regional foundation location."
}
output "network_name" {
  value       = google_compute_network.lab.name
  description = "Dedicated VPC used by Batch worker VMs."
}
output "network_self_link" {
  value       = google_compute_network.lab.self_link
  description = "VPC URL passed to the Batch job configuration."
}
output "subnetwork_name" {
  value       = google_compute_subnetwork.workers.name
  description = "Worker subnet with Private Google Access enabled."
}
output "subnetwork_self_link" {
  value       = google_compute_subnetwork.workers.self_link
  description = "Subnet URL passed to the Batch job configuration."
}
output "artifact_registry_repository" {
  value       = google_artifact_registry_repository.worker.name
  description = "Private Docker repository for the worker image."
}
output "worker_image_path" {
  value       = "${google_artifact_registry_repository.worker.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.worker.repository_id}/worker"
  description = "Tag this path during Cloud Build, then use the returned digest for Batch."
}
output "build_service_account" {
  value       = google_service_account.build.email
  description = "Custom Cloud Build identity."
}
output "runtime_service_account" {
  value       = google_service_account.runtime.email
  description = "Custom identity attached to Batch worker VMs."
}
output "input_bucket" {
  value       = google_storage_bucket.input.name
  description = "Private source shards and manifests."
}
output "attempt_output_bucket" {
  value       = google_storage_bucket.attempt.name
  description = "Worker-created, attempt-scoped results."
}
output "published_manifest_bucket" {
  value       = google_storage_bucket.published.name
  description = "Operator-only completion manifests."
}
