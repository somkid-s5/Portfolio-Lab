output "region" { value = var.region }
output "network_name" { value = google_compute_network.lab.name }
output "subnet_name" { value = google_compute_subnetwork.run_egress.name }
output "sql_instance_name" { value = google_sql_database_instance.primary.name }
output "sql_connection_name" { value = google_sql_database_instance.primary.connection_name }
output "artifact_repository" { value = google_artifact_registry_repository.app.repository_id }
output "migrator_identity" { value = google_service_account.workload["migrator"].email }
