output "project_id" { value = var.project_id }
output "network" { value = google_compute_network.orders.id }
output "subnets" { value = { for k, v in google_compute_subnetwork.tier : k => v.id } }
output "service_accounts" { value = { for k, v in google_service_account.tier : k => v.email } }
output "sql_connection_name" { value = google_sql_database_instance.orders.connection_name }
output "sql_private_ip" { value = google_sql_database_instance.orders.private_ip_address }
output "artifact_bucket" { value = google_storage_bucket.releases.name }
