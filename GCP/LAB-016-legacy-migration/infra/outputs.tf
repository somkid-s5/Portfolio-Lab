output "project_id" { value = var.project_id }
output "region" { value = var.region }
output "zone" { value = var.zone }
output "network_name" { value = google_compute_network.lab.name }
output "source_subnet_name" { value = google_compute_subnetwork.source.name }
output "run_egress_subnet_name" { value = google_compute_subnetwork.run_egress.name }
output "source_vm_name" { value = google_compute_instance.source.name }
output "source_vm_internal_ip" { value = google_compute_instance.source.network_interface[0].network_ip }
output "cloud_sql_instance" { value = google_sql_database_instance.target.name }
output "cloud_sql_connection_name" { value = google_sql_database_instance.target.connection_name }
output "cloud_sql_private_ip" { value = google_sql_database_instance.target.private_ip_address }
output "orders_image_repository" {
  value = format("%s-docker.pkg.dev/%s/%s", var.region, var.project_id, google_artifact_registry_repository.orders.repository_id)
}
output "run_runtime_service_account" { value = google_service_account.run_runtime.email }
output "source_vm_service_account" { value = google_service_account.source_vm.email }
output "target_db_secret_name" { value = google_secret_manager_secret.target_db_password.secret_id }
output "run_egress_cidr" { value = google_compute_subnetwork.run_egress.ip_cidr_range }
output "psa_reserved_range" { value = google_compute_global_address.psa_range.address }
