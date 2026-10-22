# Prerequisite: foundation applied, releases uploaded and DB bootstrapped.
# Terraform owns templates/MIGs/LBs, not secret payloads or database initialization.
data "google_compute_network" "orders" { name = "lab005-vpc" }
data "google_compute_subnetwork" "tier" {
  for_each = toset(["web", "api"])
  name = "lab005-${each.key}-subnet"
  region = "asia-southeast1"
}
data "google_service_account" "tier" {
  for_each = toset(["web", "api"])
  account_id = "lab005-${each.key}"
}
locals {
  tiers = { web = { port = 80, replicas = 2 }, api = { port = 8080, replicas = var.api_replicas } }
  bootstrap_code = base64encode(jsonencode({
    "release.py" = file("${path.module}/../../scripts/release.py")
    "vm-install.py" = file("${path.module}/../../scripts/vm-install.py")
  }))
}
resource "google_compute_address" "api" {
  name = "lab005-api-vip"
  region = "asia-southeast1"
  address_type = "INTERNAL"
  subnetwork = data.google_compute_subnetwork.tier["api"].id
  address = "10.55.20.10"
}
resource "google_compute_instance_template" "tier" {
  for_each = local.tiers
  name_prefix = "lab005-${each.key}-"
  machine_type = "e2-small"
  region = "asia-southeast1"
  labels = { lab = "lab005", tier = each.key }
  disk {
    source_image = var.debian_image
    auto_delete = true
    boot = true
    disk_size_gb = 10
    disk_type = "pd-balanced"
  }
  network_interface {
    subnetwork = data.google_compute_subnetwork.tier[each.key].id
    # No access_config: no public VM IP.
  }
  service_account {
    email = data.google_service_account.tier[each.key].email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  metadata = merge({
    enable-oslogin = "TRUE"
    block-project-ssh-keys = "TRUE"
    lab005-managed = "true"
    lab005-tier = each.key
    lab005-artifact-bucket = var.artifact_bucket
    lab005-artifact-sha256 = var.release_sha256[each.key]
    lab005-bootstrap-code = local.bootstrap_code
  }, each.key == "web" ? {
    lab005-api-vip = google_compute_address.api.address
  } : {
    lab005-sql-instance = "${var.project_id}:asia-southeast1:lab005-sql"
    lab005-db-version = var.secret_versions.db
    lab005-auth-version = var.secret_versions.auth
  })
  metadata_startup_script = file("${path.module}/../../scripts/startup.sh")
  shielded_instance_config {
    enable_secure_boot = true
    enable_vtpm = true
    enable_integrity_monitoring = true
  }
  lifecycle { create_before_destroy = true }
}
resource "google_compute_health_check" "tier" {
  for_each = local.tiers
  name = "lab005-${each.key}-live"
  check_interval_sec = 10
  timeout_sec = 3
  healthy_threshold = 2
  unhealthy_threshold = 2
  http_health_check {
    port = each.value.port
    request_path = "/livez"
  }
}
resource "google_compute_region_instance_group_manager" "tier" {
  for_each = local.tiers
  name = "lab005-${each.key}-mig"
  base_instance_name = "lab005-${each.key}"
  region = "asia-southeast1"
  distribution_policy_zones = ["asia-southeast1-a", "asia-southeast1-b"]
  target_size = each.value.replicas
  version { instance_template = google_compute_instance_template.tier[each.key].id }
  named_port {
    name = "http"
    port = each.value.port
  }
  auto_healing_policies {
    health_check = google_compute_health_check.tier[each.key].id
    initial_delay_sec = 300
  }
  update_policy {
    type = "PROACTIVE"
    minimal_action = "REPLACE"
    replacement_method = "SUBSTITUTE"
    max_surge_fixed = 2
    max_unavailable_fixed = 0
    min_ready_sec = 30
  }
}
resource "google_compute_region_backend_service" "api" {
  name = "lab005-api-internal"
  region = "asia-southeast1"
  protocol = "TCP"
  load_balancing_scheme = "INTERNAL"
  health_checks = [google_compute_health_check.tier["api"].id]
  connection_draining_timeout_sec = 30
  backend {
    group = google_compute_region_instance_group_manager.tier["api"].instance_group
    balancing_mode = "CONNECTION"
  }
}
resource "google_compute_forwarding_rule" "api" {
  name = "lab005-api-internal"
  region = "asia-southeast1"
  load_balancing_scheme = "INTERNAL"
  ip_protocol = "TCP"
  ports = ["8080"]
  network = data.google_compute_network.orders.id
  subnetwork = data.google_compute_subnetwork.tier["api"].id
  ip_address = google_compute_address.api.address
  backend_service = google_compute_region_backend_service.api.id
  allow_global_access = false
}
resource "google_compute_global_address" "web" { name = "lab005-https-ip" }
resource "google_compute_backend_service" "web" {
  name = "lab005-web-public"
  protocol = "HTTP"
  port_name = "http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec = 30
  connection_draining_timeout_sec = 30
  health_checks = [google_compute_health_check.tier["web"].id]
  backend {
    group = google_compute_region_instance_group_manager.tier["web"].instance_group
    balancing_mode = "UTILIZATION"
    max_utilization = 0.8
  }
  log_config {
    enable = true
    sample_rate = 1.0
  }
}
resource "google_compute_url_map" "web" {
  name = "lab005-web"
  default_service = google_compute_backend_service.web.id
}
resource "google_compute_managed_ssl_certificate" "web" {
  name = "lab005-web"
  managed { domains = [var.domain] }
}
resource "google_compute_target_https_proxy" "web" {
  name = "lab005-web"
  url_map = google_compute_url_map.web.id
  ssl_certificates = [google_compute_managed_ssl_certificate.web.id]
}
resource "google_compute_global_forwarding_rule" "web" {
  name = "lab005-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address = google_compute_global_address.web.address
  port_range = "443"
  target = google_compute_target_https_proxy.web.id
}
