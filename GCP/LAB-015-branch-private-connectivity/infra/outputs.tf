output "inventory_service_uri" {
  description = "Cloud Run audience URI; probe requests still use the private DNS/LB URL."
  value       = google_cloud_run_v2_service.inventory.uri
}

output "inventory_private_url" {
  description = "Private URL reachable from an authorized VPC after VPN/DNS are ready."
  value       = "http://inventory.lab.internal"
}

output "inventory_vip" {
  value = google_compute_address.inventory_vip.address
}

output "branch_probe_instance" {
  value = google_compute_instance.branch_probe.name
}

output "branch_change_probe_instance" {
  value = var.branch_additional_cidr == "" ? null : google_compute_instance.branch_change_probe[0].name
}

output "enabled_tunnel_pairs" {
  value = var.simulate_tunnel_a_failure ? ["b"] : ["a", "b"]
}
