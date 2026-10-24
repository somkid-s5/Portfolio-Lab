locals {
  enabled_apis = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
    "dns.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "serviceusage.googleapis.com",
  ])

  tunnel_pairs = {
    a = {
      hub_range        = "169.254.15.1/30"
      branch_range     = "169.254.15.2/30"
      hub_peer_ip      = "169.254.15.2"
      branch_peer_ip   = "169.254.15.1"
      hub_interface    = 0
      branch_interface = 0
    }
    b = {
      hub_range        = "169.254.16.1/30"
      branch_range     = "169.254.16.2/30"
      hub_peer_ip      = "169.254.16.2"
      branch_peer_ip   = "169.254.16.1"
      hub_interface    = 1
      branch_interface = 1
    }
  }

  active_tunnel_pairs      = var.simulate_tunnel_a_failure ? { for key, value in local.tunnel_pairs : key => value if key != "a" } : local.tunnel_pairs
  hub_advertised_ranges    = ["10.60.0.0/24"]
  branch_advertised_ranges = compact(["10.70.0.0/24", var.branch_additional_cidr])
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "enabled" {
  for_each                   = local.enabled_apis
  project                    = var.project_id
  service                    = each.value
  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "lab015-runtime"
  display_name = "Lab 15 Inventory API runtime"
  description  = "Runtime identity for the synthetic private Inventory API."
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "branch_probe" {
  project      = var.project_id
  account_id   = "lab015-branch-probe"
  display_name = "Lab 15 branch API probe"
  description  = "Identity allowed to invoke only the Lab 15 Inventory API."
  depends_on   = [google_project_service.enabled]
}

resource "google_service_account" "builder" {
  project      = var.project_id
  account_id   = "lab015-builder"
  display_name = "Lab 15 image builder"
  description  = "Builds and pushes only the Lab 15 Inventory API image."
  depends_on   = [google_project_service.enabled]
}

resource "google_project_iam_member" "operator_access" {
  for_each = toset([
    "roles/compute.viewer",
    "roles/compute.osLogin",
    "roles/iap.tunnelResourceAccessor",
  ])
  project = var.project_id
  role    = each.value
  member  = format("user:%s", var.operator_email)
}

resource "google_service_account_iam_member" "operator_act_as" {
  for_each = toset(["runtime", "builder", "branch-probe"])
  service_account_id = each.key == "runtime" ? google_service_account.runtime.name : (
    each.key == "builder" ? google_service_account.builder.name : google_service_account.branch_probe.name
  )
  role   = "roles/iam.serviceAccountUser"
  member = format("user:%s", var.operator_email)
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "lab015-images"
  description   = "Container images for the Lab 15 Inventory API."
  format        = "DOCKER"
  labels        = { lab = "lab015" }
  depends_on    = [google_project_service.enabled]
}

resource "google_artifact_registry_repository_iam_member" "builder_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.writer"
  member     = format("serviceAccount:%s", google_service_account.builder.email)
}

resource "google_project_iam_member" "builder_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = format("serviceAccount:%s", google_service_account.builder.email)
}

resource "google_project_service_identity" "cloudbuild" {
  provider   = google-beta
  project    = var.project_id
  service    = "cloudbuild.googleapis.com"
  depends_on = [google_project_service.enabled["cloudbuild.googleapis.com"]]
}

resource "google_service_account_iam_member" "cloudbuild_act_as_builder" {
  service_account_id = google_service_account.builder.name
  role               = "roles/iam.serviceAccountUser"
  member             = format("serviceAccount:%s", google_project_service_identity.cloudbuild.email)
}

resource "google_cloud_run_v2_service" "inventory" {
  project             = var.project_id
  name                = "lab015-inventory"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false

  template {
    service_account                  = google_service_account.runtime.email
    max_instance_request_concurrency = 20
    timeout                          = "30s"
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.container_image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }
  depends_on = [google_project_service.enabled["run.googleapis.com"], google_service_account_iam_member.operator_act_as]
}

resource "google_cloud_run_v2_service_iam_member" "branch_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.inventory.location
  name     = google_cloud_run_v2_service.inventory.name
  role     = "roles/run.invoker"
  member   = format("serviceAccount:%s", google_service_account.branch_probe.email)
}

resource "google_compute_network" "hub" {
  project                 = var.project_id
  name                    = "lab015-hub-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  depends_on              = [google_project_service.enabled["compute.googleapis.com"]]
}

resource "google_compute_network" "branch" {
  project                 = var.project_id
  name                    = "lab015-branch-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  depends_on              = [google_project_service.enabled["compute.googleapis.com"]]
}

resource "google_compute_subnetwork" "hub" {
  project                  = var.project_id
  name                     = "lab015-hub-subnet"
  region                   = var.region
  network                  = google_compute_network.hub.id
  ip_cidr_range            = "10.60.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_subnetwork" "hub_proxy_only" {
  project       = var.project_id
  name          = "lab015-hub-proxy-only"
  region        = var.region
  network       = google_compute_network.hub.id
  ip_cidr_range = "10.60.1.0/26"
  purpose       = "REGIONAL_MANAGED_PROXY"
  role          = "ACTIVE"
}

resource "google_compute_subnetwork" "branch" {
  project                  = var.project_id
  name                     = "lab015-branch-subnet"
  region                   = var.region
  network                  = google_compute_network.branch.id
  ip_cidr_range            = "10.70.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_subnetwork" "branch_change" {
  count                    = var.branch_additional_cidr == "" ? 0 : 1
  project                  = var.project_id
  name                     = "lab015-branch-change-subnet"
  region                   = var.region
  network                  = google_compute_network.branch.id
  ip_cidr_range            = var.branch_additional_cidr
  private_ip_google_access = true
}

resource "google_compute_firewall" "iap_ssh" {
  project       = var.project_id
  name          = "lab015-branch-allow-iap-ssh"
  network       = google_compute_network.branch.name
  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["lab015-iap-probe"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "allow_inventory_egress" {
  project            = var.project_id
  name               = "lab015-branch-allow-inventory"
  network            = google_compute_network.branch.name
  direction          = "EGRESS"
  priority           = 1000
  destination_ranges = ["10.60.0.10/32"]
  target_tags        = ["lab015-iap-probe"]
  allow {
    protocol = "tcp"
    ports    = ["80"]
  }
}

resource "google_compute_firewall" "deny_other_egress" {
  project            = var.project_id
  name               = "lab015-branch-deny-other-egress"
  network            = google_compute_network.branch.name
  direction          = "EGRESS"
  priority           = 2000
  destination_ranges = ["0.0.0.0/0"]
  target_tags        = ["lab015-iap-probe"]
  deny {
    protocol = "all"
  }
}

resource "google_compute_instance" "branch_probe" {
  project                   = var.project_id
  name                      = "lab015-branch-probe"
  zone                      = var.zone
  machine_type              = "e2-micro"
  tags                      = ["lab015-iap-probe"]
  allow_stopping_for_update = true
  deletion_protection       = false
  boot_disk {
    initialize_params {
      image = "projects/debian-cloud/global/images/family/debian-12"
      size  = 10
      type  = "pd-balanced"
    }
  }
  network_interface {
    subnetwork = google_compute_subnetwork.branch.id
  }
  service_account {
    email  = google_service_account.branch_probe.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  metadata = {
    enable-oslogin = "TRUE"
  }
  labels     = { lab = "lab015", role = "branch-probe" }
  depends_on = [google_project_iam_member.operator_access, google_service_account_iam_member.operator_act_as]
}

resource "google_compute_instance" "branch_change_probe" {
  count                     = var.branch_additional_cidr == "" ? 0 : 1
  project                   = var.project_id
  name                      = "lab015-branch-probe-change"
  zone                      = var.zone
  machine_type              = "e2-micro"
  tags                      = ["lab015-iap-probe"]
  allow_stopping_for_update = true
  deletion_protection       = false
  boot_disk {
    initialize_params {
      image = "projects/debian-cloud/global/images/family/debian-12"
      size  = 10
      type  = "pd-balanced"
    }
  }
  network_interface {
    subnetwork = google_compute_subnetwork.branch_change[0].id
  }
  service_account {
    email  = google_service_account.branch_probe.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
  metadata = {
    enable-oslogin = "TRUE"
  }
  labels     = { lab = "lab015", role = "branch-change-probe" }
  depends_on = [google_project_iam_member.operator_access, google_service_account_iam_member.operator_act_as]
}

resource "google_compute_router" "hub" {
  project = var.project_id
  name    = "lab015-hub-router"
  region  = var.region
  network = google_compute_network.hub.id
  bgp {
    asn                = 64514
    advertise_mode     = "CUSTOM"
    keepalive_interval = 20
    dynamic "advertised_ip_ranges" {
      for_each = local.hub_advertised_ranges
      content {
        range       = advertised_ip_ranges.value
        description = "Lab 15 approved hub service prefix"
      }
    }
  }
}

resource "google_compute_router" "branch" {
  project = var.project_id
  name    = "lab015-branch-router"
  region  = var.region
  network = google_compute_network.branch.id
  bgp {
    asn                = 64515
    advertise_mode     = "CUSTOM"
    keepalive_interval = 20
    dynamic "advertised_ip_ranges" {
      for_each = local.branch_advertised_ranges
      content {
        range       = advertised_ip_ranges.value
        description = "Lab 15 approved branch prefix"
      }
    }
  }
}

resource "google_compute_ha_vpn_gateway" "hub" {
  project = var.project_id
  name    = "lab015-hub-vpn"
  region  = var.region
  network = google_compute_network.hub.id
}

resource "google_compute_ha_vpn_gateway" "branch" {
  project = var.project_id
  name    = "lab015-branch-vpn"
  region  = var.region
  network = google_compute_network.branch.id
}

resource "google_compute_vpn_tunnel" "hub" {
  for_each                 = local.active_tunnel_pairs
  project                  = var.project_id
  name                     = format("lab015-hub-to-branch-%s", each.key)
  region                   = var.region
  router                   = google_compute_router.hub.name
  vpn_gateway              = google_compute_ha_vpn_gateway.hub.id
  vpn_gateway_interface    = each.value.hub_interface
  peer_gcp_gateway         = google_compute_ha_vpn_gateway.branch.id
  shared_secret_wo         = each.key == "a" ? var.vpn_shared_secret_a : var.vpn_shared_secret_b
  shared_secret_wo_version = var.vpn_secret_version
  ike_version              = 2
}

resource "google_compute_vpn_tunnel" "branch" {
  for_each                 = local.active_tunnel_pairs
  project                  = var.project_id
  name                     = format("lab015-branch-to-hub-%s", each.key)
  region                   = var.region
  router                   = google_compute_router.branch.name
  vpn_gateway              = google_compute_ha_vpn_gateway.branch.id
  vpn_gateway_interface    = each.value.branch_interface
  peer_gcp_gateway         = google_compute_ha_vpn_gateway.hub.id
  shared_secret_wo         = each.key == "a" ? var.vpn_shared_secret_a : var.vpn_shared_secret_b
  shared_secret_wo_version = var.vpn_secret_version
  ike_version              = 2
}

resource "google_compute_router_interface" "hub" {
  for_each   = local.active_tunnel_pairs
  project    = var.project_id
  name       = format("lab015-hub-if-%s", each.key)
  region     = var.region
  router     = google_compute_router.hub.name
  vpn_tunnel = google_compute_vpn_tunnel.hub[each.key].id
  ip_range   = each.value.hub_range
}

resource "google_compute_router_interface" "branch" {
  for_each   = local.active_tunnel_pairs
  project    = var.project_id
  name       = format("lab015-branch-if-%s", each.key)
  region     = var.region
  router     = google_compute_router.branch.name
  vpn_tunnel = google_compute_vpn_tunnel.branch[each.key].id
  ip_range   = each.value.branch_range
}

resource "google_compute_router_peer" "hub" {
  for_each                  = local.active_tunnel_pairs
  project                   = var.project_id
  name                      = format("lab015-hub-peer-%s", each.key)
  region                    = var.region
  router                    = google_compute_router.hub.name
  interface                 = google_compute_router_interface.hub[each.key].name
  peer_asn                  = 64515
  peer_ip_address           = each.value.hub_peer_ip
  advertised_route_priority = 100
}

resource "google_compute_router_peer" "branch" {
  for_each                  = local.active_tunnel_pairs
  project                   = var.project_id
  name                      = format("lab015-branch-peer-%s", each.key)
  region                    = var.region
  router                    = google_compute_router.branch.name
  interface                 = google_compute_router_interface.branch[each.key].name
  peer_asn                  = 64514
  peer_ip_address           = each.value.branch_peer_ip
  advertised_route_priority = 100
}

resource "google_compute_address" "inventory_vip" {
  project      = var.project_id
  name         = "lab015-inventory-vip"
  region       = var.region
  address      = "10.60.0.10"
  address_type = "INTERNAL"
  subnetwork   = google_compute_subnetwork.hub.id
  purpose      = "SHARED_LOADBALANCER_VIP"
}

resource "google_compute_region_network_endpoint_group" "inventory" {
  project               = var.project_id
  name                  = "lab015-inventory-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.inventory.name
  }
}

resource "google_compute_region_backend_service" "inventory" {
  project               = var.project_id
  name                  = "lab015-inventory-backend"
  region                = var.region
  load_balancing_scheme = "INTERNAL_MANAGED"
  protocol              = "HTTP"
  timeout_sec           = 30
  backend {
    group = google_compute_region_network_endpoint_group.inventory.id
  }
}

resource "google_compute_region_url_map" "inventory" {
  project         = var.project_id
  name            = "lab015-inventory-map"
  region          = var.region
  default_service = google_compute_region_backend_service.inventory.id
}

resource "google_compute_region_target_http_proxy" "inventory" {
  project = var.project_id
  name    = "lab015-inventory-http-proxy"
  region  = var.region
  url_map = google_compute_region_url_map.inventory.id
}

resource "google_compute_forwarding_rule" "inventory" {
  project               = var.project_id
  name                  = "lab015-inventory-ilb"
  region                = var.region
  load_balancing_scheme = "INTERNAL_MANAGED"
  ip_protocol           = "TCP"
  port_range            = "80"
  network               = google_compute_network.hub.id
  subnetwork            = google_compute_subnetwork.hub.id
  ip_address            = google_compute_address.inventory_vip.address
  target                = google_compute_region_target_http_proxy.inventory.id
  allow_global_access   = false
}

resource "google_dns_managed_zone" "private" {
  project    = var.project_id
  name       = "lab015-private"
  dns_name   = "lab.internal."
  visibility = "private"
  private_visibility_config {
    networks {
      network_url = google_compute_network.hub.id
    }
    dynamic "networks" {
      for_each = var.authorize_branch_dns ? [google_compute_network.branch.id] : []
      content {
        network_url = networks.value
      }
    }
  }
}

resource "google_dns_record_set" "inventory" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.private.name
  name         = "inventory.lab.internal."
  type         = "A"
  ttl          = 60
  rrdatas      = [google_compute_address.inventory_vip.address]
}
