output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

output "vpc_name" {
  value = google_compute_network.lab.name
}

output "run_subnet_name" {
  value = google_compute_subnetwork.run_egress.name
}

output "primary_instance_name" {
  value = google_sql_database_instance.primary.name
}

output "primary_private_ip" {
  value = google_sql_database_instance.primary.private_ip_address
}

output "database_name" {
  value = google_sql_database.records.name
}

output "bucket_name" {
  value = google_storage_bucket.attachments.name
}

output "secret_id" {
  value = google_secret_manager_secret.db_password.secret_id
}

output "admin_secret_id" {
  value = google_secret_manager_secret.db_admin_password.secret_id
}

output "artifact_repository" {
  value = google_artifact_registry_repository.app.repository_id
}

output "runtime_service_account" {
  value = google_service_account.run_runtime.email
}
