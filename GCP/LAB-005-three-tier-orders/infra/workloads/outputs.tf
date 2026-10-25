output "https_ip" { value = google_compute_global_address.web.address }
output "api_vip" { value = google_compute_address.api.address }
output "url" { value = "https://${var.domain}" }
output "instance_templates" { value = { for k,v in google_compute_instance_template.tier : k => v.id } }
output "migs" { value = { for k,v in google_compute_region_instance_group_manager.tier : k => v.name } }
