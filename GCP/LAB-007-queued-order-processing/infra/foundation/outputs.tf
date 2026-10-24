output "region" {
  value = "asia-southeast1"
}

output "sql_instance_connection_name" {
  value = google_sql_database_instance.orders.connection_name
}

output "network_name" {
  value = google_compute_network.lab007.name
}

output "run_subnet_name" {
  value = google_compute_subnetwork.run.name
}

output "artifact_image_prefix" {
  value = "asia-southeast1-docker.pkg.dev/${var.project_id}/lab007-images/order-queue"
}

output "secret_ids" {
  value = { for role, secret in google_secret_manager_secret.lab007 : role => secret.secret_id }
}

output "service_accounts" {
  value = { for role, account in google_service_account.runtime : role => account.email }
}

output "pubsub_service_agent_email" {
  value = google_project_service_identity.pubsub.email
}
