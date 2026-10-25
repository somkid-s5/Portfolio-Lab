output "cluster_name" {
  description = "Regional GKE Autopilot cluster name."
  value       = google_container_cluster.quote.name
}

output "cluster_region" {
  description = "Region containing the cluster and its DNS-based control plane."
  value       = google_container_cluster.quote.location
}

output "gateway_address_name" {
  description = "Regional address name referenced by the Kubernetes Gateway."
  value       = google_compute_address.gateway.name
}

output "gateway_ip" {
  description = "Regional external address reserved for the GKE Gateway."
  value       = google_compute_address.gateway.address
}

output "image_repository" {
  description = "Full Artifact Registry image path; append /quote-engine and a build digest."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/quote-engine"
}

output "node_service_account" {
  description = "Custom GKE node identity; it is not used by application Pods."
  value       = google_service_account.node.email
}

output "build_service_account" {
  description = "Least-privilege identity selected by cloudbuild.yaml."
  value       = google_service_account.build.email
}

output "workload_identity_pool" {
  description = "GKE Workload Identity Federation pool used by the two Kubernetes service accounts."
  value       = google_container_cluster.quote.workload_identity_config[0].workload_pool
}
