# Optional negative-access client: same subnet is NOT enough to reach API.
data "google_service_account" "diagnostic" { account_id = "lab005-diagnostic" }
resource "google_compute_instance" "diagnostic" {
  count = var.enable_diagnostic ? 1 : 0
  name = "lab005-diagnostic"
  machine_type = "e2-micro"
  zone = "asia-southeast1-a"
  labels = { lab = "lab005", purpose = "negative-access-test" }
  boot_disk {
    auto_delete = true
    initialize_params {
      image = var.debian_image
      size = 10
      type = "pd-balanced"
    }
  }
  network_interface { subnetwork = data.google_compute_subnetwork.tier["web"].id }
  service_account {
    email = data.google_service_account.diagnostic.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  metadata = {
    enable-oslogin = "TRUE"
    block-project-ssh-keys = "TRUE"
  }
  shielded_instance_config {
    enable_secure_boot = true
    enable_vtpm = true
    enable_integrity_monitoring = true
  }
}
