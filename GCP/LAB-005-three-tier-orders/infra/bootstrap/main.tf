# One-time initializer only. Save sanitized startup result, then destroy this root.
# Reboot/recreate does NOT reset an existing application role: init-db refuses it.
data "google_compute_subnetwork" "api" {
  name = "lab005-api-subnet"
  region = "asia-southeast1"
}
data "google_service_account" "bootstrap" { account_id = "lab005-bootstrap" }
resource "google_compute_instance" "init" {
  name = "lab005-init"
  machine_type = "e2-small"
  zone = "asia-southeast1-a"
  labels = { lab = "lab005", purpose = "one-time-init" }
  boot_disk {
    auto_delete = true
    initialize_params {
      image = var.debian_image
      size = 10
      type = "pd-balanced"
    }
  }
  network_interface {
    subnetwork = data.google_compute_subnetwork.api.id
    # Private only; foundation NAT provides package/artifact/API egress.
  }
  service_account {
    email = data.google_service_account.bootstrap.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  metadata = {
    enable-oslogin = "TRUE"
    block-project-ssh-keys = "TRUE"
    lab005-managed = "true"
    lab005-tier = "init"
    lab005-artifact-bucket = var.artifact_bucket
    lab005-artifact-sha256 = var.api_sha256
    lab005-sql-instance = "${var.project_id}:asia-southeast1:lab005-sql"
    lab005-db-version = var.secret_versions.db
    lab005-admin-version = var.secret_versions.admin
    lab005-bootstrap-code = base64encode(jsonencode({
      "release.py" = file("${path.module}/../../scripts/release.py")
      "vm-install.py" = file("${path.module}/../../scripts/vm-install.py")
    }))
  }
  metadata_startup_script = file("${path.module}/../../scripts/startup.sh")
  shielded_instance_config {
    enable_secure_boot = true
    enable_vtpm = true
    enable_integrity_monitoring = true
  }
}
output "initializer" {
  value = { name = google_compute_instance.init.name, zone = google_compute_instance.init.zone }
}
