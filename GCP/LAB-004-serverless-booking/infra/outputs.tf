output "network" {
  value = google_compute_network.booking.name
}
output "subnet" {
  value = google_compute_subnetwork.run.name
}
output "instance_connection_name" {
  value = google_sql_database_instance.booking.connection_name
}
output "runtime_service_account" {
  value = google_service_account.runtime.email
}
output "bootstrap_service_account" {
  value = google_service_account.bootstrap.email
}
output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
