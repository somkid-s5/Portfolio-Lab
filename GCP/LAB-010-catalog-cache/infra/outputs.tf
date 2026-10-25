output "run_subnet" {
  description = "Cloud Run Direct VPC egress subnet; private service ranges use separate PSA allocation."
  value       = google_compute_subnetwork.run.name
}

output "cloud_sql_private_ip" {
  description = "Private address only; the instance has no public IPv4."
  value       = google_sql_database_instance.catalog.private_ip_address
}

output "redis_private_host" {
  description = "Memorystore private IP and TLS port; AUTH is never output."
  value       = google_redis_instance.catalog.host
}

output "artifact_registry_repository" {
  description = "Repository for the Lab 10 app image."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "build_service_account" {
  description = "Least-privilege identity used by the explicit Cloud Build config."
  value       = google_service_account.runtime["builder"].email
}

output "database_service_accounts" {
  description = "IAM DB usernames corresponding to reader/operator/migrator identities."
  value       = local.sql_db_usernames
}

output "service_urls" {
  description = "Cloud Run URLs; null until enable_workloads=true and the digest-pinned image is provided."
  value = {
    public   = try(google_cloud_run_v2_service.catalog["public"].uri, null)
    operator = try(google_cloud_run_v2_service.catalog["operator"].uri, null)
  }
}
