# Foundation only. Workload VMs/LBs are a separate Terraform root; secrets are CLI-owned.
# Never put password values or secret_version resources in Terraform state.
locals {
  apis = toset([
    "compute.googleapis.com", "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com", "storage.googleapis.com",
    "secretmanager.googleapis.com", "logging.googleapis.com",
    "iam.googleapis.com", "cloudresourcemanager.googleapis.com",
    "iap.googleapis.com", "oslogin.googleapis.com"
  ])
  secret_names = toset(["auth", "db", "bootstrap-admin"])
}
resource "google_project_service" "api" {
  for_each = local.apis
  service = each.value
  disable_on_destroy = false
}
resource "google_compute_network" "orders" {
  name = "lab005-vpc"
  auto_create_subnetworks = false
  depends_on = [google_project_service.api]
}
resource "google_compute_subnetwork" "tier" {
  for_each = { web = "10.55.10.0/24", api = "10.55.20.0/24" }
  name = "lab005-${each.key}-subnet"
  region = "asia-southeast1"
  network = google_compute_network.orders.id
  ip_cidr_range = each.value
  private_ip_google_access = true
}
resource "google_compute_router" "outbound" {
  name = "lab005-router"
  region = "asia-southeast1"
  network = google_compute_network.orders.id
}
resource "google_compute_router_nat" "outbound" {
  name = "lab005-nat"
  router = google_compute_router.outbound.name
  region = "asia-southeast1"
  nat_ip_allocate_option = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  dynamic "subnetwork" {
    for_each = google_compute_subnetwork.tier
    content {
      name = subnetwork.value.id
      source_ip_ranges_to_nat = ["PRIMARY_IP_RANGE"]
    }
  }
  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
# This allocated producer range is not a workload subnet.
resource "google_compute_global_address" "sql" {
  name = "lab005-sql-psa"
  purpose = "VPC_PEERING"
  address_type = "INTERNAL"
  address = "10.85.0.0"
  prefix_length = 16
  network = google_compute_network.orders.id
}
resource "google_service_networking_connection" "sql" {
  network = google_compute_network.orders.id
  service = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql.name]
}
resource "google_sql_database_instance" "orders" {
  name = "lab005-sql"
  database_version = "POSTGRES_16"
  region = "asia-southeast1"
  deletion_protection = !var.allow_destroy
  depends_on = [google_service_networking_connection.sql]
  settings {
    tier = "db-custom-1-3840"
    edition = "ENTERPRISE"
    availability_type = "REGIONAL"
    location_preference {
      zone = "asia-southeast1-a"
      secondary_zone = "asia-southeast1-b"
    }
    disk_type = "PD_SSD"
    disk_size = 10
    disk_autoresize = false
    deletion_protection_enabled = !var.allow_destroy
    user_labels = { lab = "lab005", purpose = "training" }
    ip_configuration {
      ipv4_enabled = false
      private_network = google_compute_network.orders.id
      allocated_ip_range = google_compute_global_address.sql.name
      ssl_mode = "ENCRYPTED_ONLY"
    }
    database_flags {
      name = "max_connections"
      value = "64"
    }
    backup_configuration {
      enabled = true
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 1
      start_time = "18:00"
      backup_retention_settings {
        retained_backups = 2
        retention_unit = "COUNT"
      }
    }
  }
}
resource "google_sql_database" "orders" {
  name = "orders"
  instance = google_sql_database_instance.orders.name
}

resource "google_service_account" "tier" {
  for_each = toset(["web", "api", "bootstrap", "diagnostic"])
  account_id = "lab005-${each.value}"
  display_name = "Lab005 ${each.value}"
  depends_on = [google_project_service.api]
}
resource "google_project_iam_member" "sql_client" {
  for_each = toset(["api", "bootstrap"])
  project = var.project_id
  role = "roles/cloudsql.client"
  member = "serviceAccount:${google_service_account.tier[each.value].email}"
}
resource "google_secret_manager_secret" "orders" {
  for_each = local.secret_names
  secret_id = "lab005-${each.value}"
  replication {
    auto {}
  }
  depends_on = [google_project_service.api]
}
locals {
  secret_access = {
    api_db = { sa = "api", secret = "db" }
    api_auth = { sa = "api", secret = "auth" }
    bootstrap_db = { sa = "bootstrap", secret = "db" }
    bootstrap_admin = { sa = "bootstrap", secret = "bootstrap-admin" }
  }
}
resource "google_secret_manager_secret_iam_member" "access" {
  for_each = local.secret_access
  secret_id = google_secret_manager_secret.orders[each.value.secret].id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.tier[each.value.sa].email}"
}
resource "google_storage_bucket" "releases" {
  name = var.artifact_bucket
  location = "ASIA-SOUTHEAST1"
  uniform_bucket_level_access = true
  public_access_prevention = "enforced"
  force_destroy = false
  versioning {
    enabled = true
  }
  labels = { lab = "lab005", purpose = "training" }
  depends_on = [google_project_service.api]
}
resource "google_storage_bucket_iam_member" "read_release" {
  for_each = toset(["web", "api", "bootstrap"])
  bucket = google_storage_bucket.releases.name
  role = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.tier[each.value].email}"
}
# No allow-internal rule. Source SA is not combined with CIDR (which would be union).
resource "google_compute_firewall" "web_to_api" {
  name = "lab005-web-to-api"
  network = google_compute_network.orders.name
  source_service_accounts = [google_service_account.tier["web"].email]
  target_service_accounts = [google_service_account.tier["api"].email]
  allow {
    protocol = "tcp"
    ports = ["8080"]
  }
  log_config { metadata = "EXCLUDE_ALL_METADATA" }
}
resource "google_compute_firewall" "health" {
  for_each = { web = "80", api = "8080" }
  name = "lab005-health-${each.key}"
  network = google_compute_network.orders.name
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
  target_service_accounts = [google_service_account.tier[each.key].email]
  allow {
    protocol = "tcp"
    ports = [each.value]
  }
}
resource "google_compute_firewall" "iap" {
  name = "lab005-iap-ssh"
  network = google_compute_network.orders.name
  source_ranges = ["35.235.240.0/20"]
  target_service_accounts = [for sa in google_service_account.tier : sa.email]
  allow {
    protocol = "tcp"
    ports = ["22"]
  }
}
resource "google_compute_firewall" "web_deny_sql" {
  name = "lab005-web-deny-sql"
  network = google_compute_network.orders.name
  direction = "EGRESS"
  priority = 900
  destination_ranges = ["10.85.0.0/16"]
  target_service_accounts = [google_service_account.tier["web"].email]
  deny { protocol = "all" }
  log_config { metadata = "EXCLUDE_ALL_METADATA" }
}
