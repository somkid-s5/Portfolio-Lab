locals {
  enabled_apis = toset([
    "artifactregistry.googleapis.com", "compute.googleapis.com", "iam.googleapis.com",
    "logging.googleapis.com", "run.googleapis.com", "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com", "serviceusage.googleapis.com", "sqladmin.googleapis.com",
  ])
  labels = { lab = "lab016", managed_by = "terraform" }
}
resource "google_project_service" "enabled" {
  for_each = local.enabled_apis
  project = var.project_id
  service = each.value
  disable_on_destroy = false
  disable_dependent_services = false
}
resource "google_compute_network" "lab" {
  name = "lab016-vpc"
  auto_create_subnetworks = false
  routing_mode = "REGIONAL"
  description = "Private network for the Lab 16 legacy-to-cloud migration."
  depends_on = [google_project_service.enabled]
}
resource "google_compute_subnetwork" "source" {
  name = "lab016-source-subnet"
  region = var.region
  network = google_compute_network.lab.id
  ip_cidr_range = "10.80.0.0/24"
  private_ip_google_access = true
  description = "Legacy VM subnet; VM has no external IP."
}
resource "google_compute_subnetwork" "run_egress" {
  name = "lab016-run-egress"
  region = var.region
  network = google_compute_network.lab.id
  ip_cidr_range = "10.80.1.0/26"
  private_ip_google_access = true
  description = "Direct VPC egress subnet for the Cloud Run target."
}
resource "google_compute_global_address" "psa_range" {
  name = "lab016-psa-range"
  purpose = "VPC_PEERING"
  address_type = "INTERNAL"
  address = "10.80.2.0"
  prefix_length = 24
  network = google_compute_network.lab.id
  description = "Reserved range for the Cloud SQL service producer connection."
}
resource "google_service_networking_connection" "private_services" {
  network = google_compute_network.lab.id
  service = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
  depends_on = [google_project_service.enabled]
}
resource "google_compute_router" "egress" {
  name = "lab016-nat-router"
  region = var.region
  network = google_compute_network.lab.id
}
resource "google_compute_router_nat" "source_egress" {
  name = "lab016-source-egress"
  router = google_compute_router.egress.name
  region = var.region
  nat_ip_allocate_option = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  subnetwork {
    name = google_compute_subnetwork.source.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
  log_config { enable = true, filter = "ERRORS_ONLY" }
}
resource "google_compute_firewall" "iap_ssh" {
  name = "lab016-allow-iap-ssh"
  network = google_compute_network.lab.name
  direction = "INGRESS"
  priority = 1000
  source_ranges = ["35.235.240.0/20"]
  target_tags = ["lab016-source"]
  allow { protocol = "tcp", ports = ["22"] }
  description = "SSH to the source VM only through IAP TCP forwarding."
}
resource "google_compute_firewall" "load_balancer_backend" {
  name = "lab016-allow-lb-backend"
  network = google_compute_network.lab.name
  direction = "INGRESS"
  priority = 1000
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
  target_tags = ["lab016-source"]
  allow { protocol = "tcp", ports = ["8080"] }
  description = "Allow global Application Load Balancer proxy and health checks to Orders API."
}
resource "google_service_account" "run_runtime" {
  account_id = "lab016-run-runtime"
  display_name = "Lab 16 Cloud Run runtime"
  description = "Runtime identity for the migrated Orders API."
  depends_on = [google_project_service.enabled]
}
resource "google_service_account" "source_vm" {
  account_id = "lab016-source-vm"
  display_name = "Lab 16 legacy and migration VM"
  description = "Restricted identity for source VM logging and one migration secret."
  depends_on = [google_project_service.enabled]
}
resource "google_project_iam_member" "run_cloud_sql_client" {
  project = var.project_id
  role = "roles/cloudsql.client"
  member = format("serviceAccount:%s", google_service_account.run_runtime.email)
}
resource "google_project_iam_member" "source_log_writer" {
  project = var.project_id
  role = "roles/logging.logWriter"
  member = format("serviceAccount:%s", google_service_account.source_vm.email)
}
resource "google_artifact_registry_repository" "orders" {
  location = var.region
  repository_id = "lab016-orders"
  description = "Container images for the synthetic Orders migration target."
  format = "DOCKER"
  labels = local.labels
  depends_on = [google_project_service.enabled]
}
resource "google_secret_manager_secret" "target_db_password" {
  secret_id = "lab016-target-db-password"
  labels = local.labels
  replication { auto {} }
  depends_on = [google_project_service.enabled]
}
resource "google_secret_manager_secret_iam_member" "run_reads_target_db_password" {
  project = var.project_id
  secret_id = google_secret_manager_secret.target_db_password.secret_id
  role = "roles/secretmanager.secretAccessor"
  member = format("serviceAccount:%s", google_service_account.run_runtime.email)
}
resource "google_secret_manager_secret_iam_member" "source_reads_target_db_password" {
  project = var.project_id
  secret_id = google_secret_manager_secret.target_db_password.secret_id
  role = "roles/secretmanager.secretAccessor"
  member = format("serviceAccount:%s", google_service_account.source_vm.email)
}
resource "google_sql_database_instance" "target" {
  name = "lab016-target-pg"
  database_version = "POSTGRES_16"
  region = var.region
  deletion_protection = false
  settings {
    tier = var.sql_tier
    availability_type = "ZONAL"
    disk_type = "PD_SSD"
    disk_size = 10
    disk_autoresize = true
    user_labels = local.labels
    backup_configuration { enabled = true, start_time = "17:00" }
    ip_configuration {
      ipv4_enabled = false
      private_network = google_compute_network.lab.id
      allocated_ip_range = google_compute_global_address.psa_range.name
    }
  }
  depends_on = [google_project_service.enabled, google_service_networking_connection.private_services]
}
resource "google_sql_database" "orders" {
  name = "orders"
  instance = google_sql_database_instance.target.name
  charset = "UTF8"
  collation = "en_US.UTF8"
}
resource "google_compute_instance" "source" {
  name = "lab016-source"
  machine_type = var.source_machine_type
  zone = var.zone
  tags = ["lab016-source"]
  labels = local.labels
  boot_disk {
    initialize_params { image = "debian-cloud/debian-12", size = 20, type = "pd-balanced" }
  }
  network_interface { subnetwork = google_compute_subnetwork.source.id }
  service_account {
    email = google_service_account.source_vm.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  metadata_startup_script = file("../scripts/source-startup.sh")
  shielded_instance_config {
    enable_secure_boot = true
    enable_vtpm = true
    enable_integrity_monitoring = true
  }
  scheduling { automatic_restart = true, on_host_maintenance = "MIGRATE" }
  depends_on = [
    google_compute_router_nat.source_egress,
    google_compute_firewall.iap_ssh,
    google_compute_firewall.load_balancer_backend,
    google_service_account.source_vm,
  ]
}
