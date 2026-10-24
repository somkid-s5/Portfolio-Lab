locals {
  enabled_apis = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudtasks.googleapis.com",
    "datastore.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
  ])

  runtime_accounts = {
    event_api  = "event-api"
    reconciler = "reconciler"
    worker     = "worker"
    scheduler  = "scheduler-caller"
    task_oidc  = "task-oidc"
  }

  simulator_accounts = {
    for partner_id, _ in var.partners :
    "simulator_${partner_id}" => "sim-${partner_id}"
  }

  all_accounts = merge(local.runtime_accounts, local.simulator_accounts)

  receipt_bucket_names = {
    for partner_id, _ in var.partners :
    partner_id => "l9-${substr(sha256("${var.project_id}/${partner_id}"), 0, 10)}-${var.bucket_suffix}-${partner_id}-r"
  }

  queue_runtime_config = var.enable_workloads ? [
    for partner_id, _ in var.partners : {
      project_id           = var.project_id
      location_id          = var.region
      queue_id             = partner_id
      partner_id           = partner_id
      worker_url           = "${google_cloud_run_v2_service.worker[0].uri}/internal/deliver"
      task_service_account = google_service_account.runtime["task_oidc"].email
      oidc_audience        = google_cloud_run_v2_service.worker[0].uri
    }
  ] : []

  worker_endpoint_config = var.enable_workloads ? [
    for partner_id, partner in var.partners : {
      partner_id     = partner_id
      url            = "${google_cloud_run_v2_service.simulator[partner_id].uri}/v1/webhooks/${partner_id}"
      secret_version = "projects/${var.project_id}/secrets/lab009-${partner_id}-hmac/versions/${partner.secret_version}"
    }
  ] : []
}

data "google_project" "current" {
  project = var.project_id
}

resource "google_project_service" "api" {
  for_each           = local.enabled_apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_firestore_database" "ledger" {
  project                 = var.project_id
  name                    = "(default)"
  location_id             = var.region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = var.allow_destroy ? "DELETE_PROTECTION_DISABLED" : "DELETE_PROTECTION_ENABLED"
  deletion_policy         = var.allow_destroy ? "DELETE" : "PREVENT"

  depends_on = [google_project_service.api]
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "lab009-images"
  description   = "Private immutable container images for the Partner Webhook Relay lab."
  format        = "DOCKER"
  labels        = { lab = "lab009" }

  depends_on = [google_project_service.api]
}

resource "google_service_account" "runtime" {
  for_each     = local.all_accounts
  project      = var.project_id
  account_id   = "lab009-${each.value}"
  display_name = "Lab 09 ${each.value} workload identity"

  depends_on = [google_project_service.api]
}

resource "google_project_service_identity" "cloud_tasks" {
  provider = google-beta
  project  = var.project_id
  service  = "cloudtasks.googleapis.com"

  depends_on = [google_project_service.api]
}

resource "google_project_service_identity" "scheduler" {
  provider = google-beta
  project  = var.project_id
  service  = "cloudscheduler.googleapis.com"

  depends_on = [google_project_service.api]
}

resource "google_service_account_iam_member" "cloud_tasks_can_sign" {
  service_account_id = google_service_account.runtime["task_oidc"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudtasks.iam.gserviceaccount.com"

  depends_on = [google_project_service_identity.cloud_tasks]
}

resource "google_service_account_iam_member" "event_api_can_impersonate_task" {
  service_account_id = google_service_account.runtime["task_oidc"].name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.runtime["event_api"].member
}

resource "google_service_account_iam_member" "reconciler_can_impersonate_task" {
  service_account_id = google_service_account.runtime["task_oidc"].name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.runtime["reconciler"].member
}

resource "google_service_account_iam_member" "operator_can_configure_scheduler" {
  service_account_id = google_service_account.runtime["scheduler"].name
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}

resource "google_project_iam_member" "runtime_firestore" {
  for_each = {
    for name in ["event_api", "reconciler", "worker"] :
    name => google_service_account.runtime[name].member
  }
  project = var.project_id
  role    = "roles/datastore.user"
  member  = each.value
}

resource "google_project_iam_member" "operator" {
  for_each = toset([
    "roles/cloudscheduler.jobRunner",
    "roles/datastore.user",
    "roles/logging.viewer",
    "roles/run.viewer",
  ])
  project = var.project_id
  role    = each.value
  member  = var.operator_member
}

resource "google_artifact_registry_repository_iam_member" "operator_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.writer"
  member     = var.operator_member
}

resource "google_secret_manager_secret" "partner" {
  for_each  = var.partners
  project   = var.project_id
  secret_id = "lab009-${each.key}-hmac"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  labels = {
    lab       = "lab009"
    partner   = each.key
    component = "hmac"
  }

  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_iam_member" "worker_accessor" {
  for_each  = var.partners
  project   = var.project_id
  secret_id = google_secret_manager_secret.partner[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.runtime["worker"].member
}

resource "google_storage_bucket" "receipts" {
  for_each                    = var.partners
  project                     = var.project_id
  name                        = local.receipt_bucket_names[each.key]
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  labels = {
    lab       = "lab009"
    partner   = each.key
    component = "receipts"
  }

  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_iam_member" "simulator_accessor" {
  for_each  = var.partners
  project   = var.project_id
  secret_id = google_secret_manager_secret.partner[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.runtime["simulator_${each.key}"].member
}

resource "google_storage_bucket_iam_member" "simulator_creator" {
  for_each = var.partners
  bucket   = google_storage_bucket.receipts[each.key].name
  role     = "roles/storage.objectCreator"
  member   = google_service_account.runtime["simulator_${each.key}"].member
}

resource "google_storage_bucket_iam_member" "simulator_reader" {
  for_each = var.partners
  bucket   = google_storage_bucket.receipts[each.key].name
  role     = "roles/storage.objectViewer"
  member   = google_service_account.runtime["simulator_${each.key}"].member
}

resource "google_storage_bucket_iam_member" "operator_receipt_reader" {
  for_each = var.partners
  bucket   = google_storage_bucket.receipts[each.key].name
  role     = "roles/storage.objectViewer"
  member   = var.operator_member
}

resource "google_cloud_tasks_queue" "partner" {
  for_each = var.partners
  project  = var.project_id
  location = var.region
  name     = each.key

  rate_limits {
    max_dispatches_per_second = 1
    max_concurrent_dispatches = 1
  }

  retry_config {
    max_attempts       = 5
    max_retry_duration = "0s"
    min_backoff        = "5s"
    max_backoff        = "20s"
    max_doublings      = 2
  }

  stackdriver_logging_config {
    sampling_ratio = 1
  }

  depends_on = [google_project_service.api]
}

resource "google_cloud_tasks_queue_iam_member" "event_enqueuer" {
  for_each = google_cloud_tasks_queue.partner
  project  = var.project_id
  location = each.value.location
  name     = each.value.name
  role     = "roles/cloudtasks.enqueuer"
  member   = google_service_account.runtime["event_api"].member
}

resource "google_cloud_tasks_queue_iam_member" "reconciler_enqueuer" {
  for_each = google_cloud_tasks_queue.partner
  project  = var.project_id
  location = each.value.location
  name     = each.value.name
  role     = "roles/cloudtasks.enqueuer"
  member   = google_service_account.runtime["reconciler"].member
}

resource "google_cloud_tasks_queue_iam_member" "reconciler_viewer" {
  for_each = google_cloud_tasks_queue.partner
  project  = var.project_id
  location = each.value.location
  name     = each.value.name
  role     = "roles/cloudtasks.viewer"
  member   = google_service_account.runtime["reconciler"].member
}

resource "google_cloud_tasks_queue_iam_member" "operator_viewer" {
  for_each = google_cloud_tasks_queue.partner
  project  = var.project_id
  location = each.value.location
  name     = each.value.name
  role     = "roles/cloudtasks.viewer"
  member   = var.operator_member
}

resource "google_cloud_run_v2_service" "worker" {
  count               = var.enable_workloads ? 1 : 0
  project             = var.project_id
  name                = "lab009-worker"
  location            = var.region
  deletion_protection = !var.allow_destroy
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  labels              = { lab = "lab009", component = "worker" }

  template {
    service_account                  = google_service_account.runtime["worker"].email
    timeout                          = "20s"
    max_instance_request_concurrency = 8

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.image_uri
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      env {
        name  = "LAB09_SERVICE_ROLE"
        value = "worker"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "LAB09_PARTNER_ENDPOINTS_JSON"
        value = jsonencode(local.worker_endpoint_config)
      }
      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_firestore_database.ledger,
    google_project_iam_member.runtime_firestore,
    google_secret_manager_secret_iam_member.worker_accessor,
  ]
}

resource "google_cloud_run_v2_service" "simulator" {
  for_each            = var.enable_workloads ? var.partners : {}
  project             = var.project_id
  name                = "lab009-sim-${each.key}"
  location            = var.region
  deletion_protection = !var.allow_destroy
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = { lab = "lab009", component = "simulator", partner = each.key }

  template {
    service_account                  = google_service_account.runtime["simulator_${each.key}"].email
    timeout                          = "20s"
    max_instance_request_concurrency = 8

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.image_uri
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      env {
        name  = "LAB09_SERVICE_ROLE"
        value = "simulator"
      }
      env {
        name  = "LAB09_PARTNER_ID"
        value = each.key
      }
      env {
        name  = "LAB09_SECRET_VERSION"
        value = "projects/${var.project_id}/secrets/${google_secret_manager_secret.partner[each.key].secret_id}/versions/${var.partners[each.key].secret_version}"
      }
      env {
        name  = "LAB09_RECEIPT_BUCKET"
        value = google_storage_bucket.receipts[each.key].name
      }
      env {
        name  = "LAB09_FAULT_MODE"
        value = var.partners[each.key].fault_mode
      }
      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.simulator_accessor,
    google_storage_bucket_iam_member.simulator_creator,
    google_storage_bucket_iam_member.simulator_reader,
  ]
}

resource "google_cloud_run_v2_service" "event_api" {
  count               = var.enable_workloads ? 1 : 0
  project             = var.project_id
  name                = "lab009-event-api"
  location            = var.region
  deletion_protection = !var.allow_destroy
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = { lab = "lab009", component = "event-api" }

  template {
    service_account                  = google_service_account.runtime["event_api"].email
    timeout                          = "20s"
    max_instance_request_concurrency = 8

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.image_uri
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      env {
        name  = "LAB09_SERVICE_ROLE"
        value = "event-api"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "LAB09_PARTNER_QUEUES_JSON"
        value = jsonencode(local.queue_runtime_config)
      }
      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_firestore_database.ledger,
    google_cloud_tasks_queue.partner,
    google_cloud_tasks_queue_iam_member.event_enqueuer,
    google_service_account_iam_member.event_api_can_impersonate_task,
    google_project_iam_member.runtime_firestore,
  ]
}

resource "google_cloud_run_v2_service" "reconciler" {
  count               = var.enable_workloads ? 1 : 0
  project             = var.project_id
  name                = "lab009-reconciler"
  location            = var.region
  deletion_protection = !var.allow_destroy
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  labels              = { lab = "lab009", component = "reconciler" }

  template {
    service_account                  = google_service_account.runtime["reconciler"].email
    timeout                          = "25s"
    max_instance_request_concurrency = 1

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.image_uri
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      env {
        name  = "LAB09_SERVICE_ROLE"
        value = "reconciler"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "LAB09_PARTNER_QUEUES_JSON"
        value = jsonencode(local.queue_runtime_config)
      }
      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  depends_on = [
    google_firestore_database.ledger,
    google_cloud_tasks_queue.partner,
    google_cloud_tasks_queue_iam_member.reconciler_enqueuer,
    google_cloud_tasks_queue_iam_member.reconciler_viewer,
    google_service_account_iam_member.reconciler_can_impersonate_task,
    google_project_iam_member.runtime_firestore,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "event_producer" {
  count    = var.enable_workloads ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.event_api[0].name
  role     = "roles/run.invoker"
  member   = var.producer_member
}

resource "google_cloud_run_v2_service_iam_member" "task_invoker" {
  count    = var.enable_workloads ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker[0].name
  role     = "roles/run.invoker"
  member   = google_service_account.runtime["task_oidc"].member
}

resource "google_cloud_run_v2_service_iam_member" "scheduler_invoker" {
  count    = var.enable_workloads ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.reconciler[0].name
  role     = "roles/run.invoker"
  member   = google_service_account.runtime["scheduler"].member
}

resource "google_cloud_run_v2_service_iam_member" "simulator_public" {
  for_each = google_cloud_run_v2_service.simulator
  project  = var.project_id
  location = var.region
  name     = each.value.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_scheduler_job" "reconcile" {
  count            = var.enable_workloads ? 1 : 0
  project          = var.project_id
  region           = var.region
  name             = "lab009-reconcile-every-minute"
  description      = "Repair a bounded page of pending Lab 09 webhook deliveries."
  schedule         = "*/1 * * * *"
  time_zone        = "Etc/UTC"
  paused           = var.pause_scheduler
  attempt_deadline = "30s"

  retry_config {
    retry_count          = 1
    max_retry_duration   = "60s"
    min_backoff_duration = "5s"
    max_backoff_duration = "30s"
    max_doublings        = 2
  }

  http_target {
    uri         = "${google_cloud_run_v2_service.reconciler[0].uri}/internal/reconcile"
    http_method = "POST"
    body        = base64encode("{}")
    headers     = { "Content-Type" = "application/json" }

    oidc_token {
      service_account_email = google_service_account.runtime["scheduler"].email
      audience              = google_cloud_run_v2_service.reconciler[0].uri
    }
  }

  depends_on = [
    google_project_service_identity.scheduler,
    google_service_account_iam_member.operator_can_configure_scheduler,
    google_cloud_run_v2_service_iam_member.scheduler_invoker,
  ]
}
