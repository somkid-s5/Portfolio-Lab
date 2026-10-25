output "project_number" {
  value       = data.google_project.current.number
  description = "Project number used to identify Google-managed service agents."
}

output "region" {
  value = var.region
}

output "network_name" {
  value = google_compute_network.lab.name
}

output "subnet_name" {
  value = google_compute_subnetwork.run_egress.name
}

output "instance_connection_name" {
  value = google_sql_database_instance.primary.connection_name
}

output "cloud_sql_private_ip" {
  value = google_sql_database_instance.primary.private_ip_address
}

output "database_name" {
  value = google_sql_database.tasks.name
}

output "tasks_topic" {
  value = google_pubsub_topic.tasks.id
}

output "dead_letter_topic" {
  value = google_pubsub_topic.dead_letter.id
}

output "artifact_registry_repository" {
  value = google_artifact_registry_repository.app.repository_id
}

output "build_service_account" {
  value = google_service_account.build.email
}

output "migrator_service_account" {
  value = google_service_account.migrator.email
}

output "api_service_account" {
  value = google_service_account.api.email
}

output "worker_service_account" {
  value = google_service_account.worker.email
}

output "push_service_account" {
  value = google_service_account.pubsub_push.email
}
