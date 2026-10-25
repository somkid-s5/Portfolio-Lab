output "project_id" {
  value       = var.project_id
  description = "Project containing the Lab 12 foundation"
}
output "region" {
  value       = var.region
  description = "GKE and Gateway region"
}
output "cluster_name" {
  value       = google_container_cluster.checkout.name
  description = "GKE Autopilot cluster"
}
output "artifact_registry_repository" {
  value       = google_artifact_registry_repository.images.name
  description = "Artifact Registry resource name"
}
output "image_repository_uri" {
  value       = "${google_artifact_registry_repository.images.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/checkout"
  description = "Repository URI for the checkout image"
}
output "gateway_ip_name" {
  value       = google_compute_address.gateway.name
  description = "Named regional address referenced by the Gateway"
}
output "gateway_ip" {
  value       = google_compute_address.gateway.address
  description = "Public IPv4 address for HTTPS testing"
}
output "collector_workload_identity_principal" {
  value       = local.collector_principal
  description = "GKE KSA principal granted trace-write permission"
}
