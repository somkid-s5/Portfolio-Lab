# Foundation must be applied and the pinned image/auth version published first.
data "google_service_account" "identity" {
  for_each = toset(["portal", "worker", "trigger", "upload-signer", "download-signer"])
  account_id = "lab006-${each.value}"
}
locals {
  common_env = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    FIRESTORE_DATABASE = "lab006-files"
    INCOMING_BUCKET = var.bucket_names.incoming
    RESULTS_BUCKET = var.bucket_names.results
  }
}
resource "google_cloud_run_v2_service" "worker" {
  name = "lab006-worker"
  location = "asia-southeast1"
  ingress = "INGRESS_TRAFFIC_ALL"
  deletion_protection = !var.allow_destroy
  labels = { lab = "lab006", tier = "worker" }
  template {
    service_account = data.google_service_account.identity["worker"].email
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
    timeout = "60s"
    max_instance_request_concurrency = 1
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.image
      ports { container_port = 8080 }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }
      dynamic "env" {
        for_each = merge(local.common_env, {
          SERVICE_ROLE = "worker"
          FAIL_AFTER_OUTPUT_ONCE = tostring(var.worker_fail_after_output_once)
        })
        content {
          name = env.key
          value = env.value
        }
      }
      startup_probe {
        http_get {
          path = "/livez"
          port = 8080
        }
        period_seconds = 2
        timeout_seconds = 2
        failure_threshold = 30
      }
      liveness_probe {
        http_get {
          path = "/livez"
          port = 8080
        }
        period_seconds = 10
        timeout_seconds = 2
        failure_threshold = 3
      }
    }
  }
  traffic {
    type = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}
resource "google_cloud_run_v2_service" "portal" {
  name = "lab006-portal"
  location = "asia-southeast1"
  ingress = "INGRESS_TRAFFIC_ALL"
  deletion_protection = !var.allow_destroy
  labels = { lab = "lab006", tier = "portal" }
  template {
    service_account = data.google_service_account.identity["portal"].email
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
    timeout = "30s"
    max_instance_request_concurrency = 8
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    volumes {
      name = "auth"
      secret {
        secret = "lab006-auth"
        default_mode = 292
        items {
          version = var.auth_version
          path = "auth.json"
          mode = 292
        }
      }
    }
    containers {
      image = var.image
      ports { container_port = 8080 }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }
      volume_mounts {
        name = "auth"
        mount_path = "/secrets/auth"
      }
      dynamic "env" {
        for_each = merge(local.common_env, {
          SERVICE_ROLE = "portal"
          AUTH_FILE = "/secrets/auth/auth.json"
          UPLOAD_SIGNER = data.google_service_account.identity["upload-signer"].email
          DOWNLOAD_SIGNER = data.google_service_account.identity["download-signer"].email
          WORKER_ORIGIN = google_cloud_run_v2_service.worker.uri
          UPLOAD_LIMIT_MODE = var.upload_limit_mode
        })
        content {
          name = env.key
          value = env.value
        }
      }
      startup_probe {
        http_get {
          path = "/livez"
          port = 8080
        }
        period_seconds = 2
        timeout_seconds = 2
        failure_threshold = 30
      }
      liveness_probe {
        http_get {
          path = "/livez"
          port = 8080
        }
        period_seconds = 10
        timeout_seconds = 2
        failure_threshold = 3
      }
    }
  }
  traffic {
    type = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}
resource "google_cloud_run_v2_service_iam_member" "portal_public" {
  name = google_cloud_run_v2_service.portal.name
  location = google_cloud_run_v2_service.portal.location
  role = "roles/run.invoker"
  member = "allUsers"
}
# Worker has a reachable HTTPS URL, but no anonymous Invoker binding.
resource "google_cloud_run_v2_service_iam_member" "worker_invoker" {
  for_each = toset(["portal", "trigger"])
  name = google_cloud_run_v2_service.worker.name
  location = google_cloud_run_v2_service.worker.location
  role = "roles/run.invoker"
  member = "serviceAccount:${data.google_service_account.identity[each.value].email}"
}
resource "google_eventarc_trigger" "incoming" {
  name = "lab006-incoming-finalized"
  location = "asia-southeast1"
  service_account = data.google_service_account.identity["trigger"].email
  matching_criteria {
    attribute = "type"
    value = "google.cloud.storage.object.v1.finalized"
  }
  matching_criteria {
    attribute = "bucket"
    value = var.bucket_names.incoming
  }
  destination {
    cloud_run_service {
      service = google_cloud_run_v2_service.worker.name
      region = "asia-southeast1"
      path = "/events/storage"
    }
  }
  labels = { lab = "lab006" }
  depends_on = [google_cloud_run_v2_service_iam_member.worker_invoker]
}
