locals {
  job_name                = "lab008-daily-report"
  service_name            = "lab008-coordinator"
  report_scheduler_name   = "lab008-report-schedule"
  watchdog_scheduler_name = "lab008-watchdog"
  common_environment = {
    GOOGLE_CLOUD_PROJECT = var.project_id
    FIRESTORE_DATABASE   = var.firestore_database
    FIRESTORE_COLLECTION = var.firestore_collection
    SOURCE_BUCKET        = var.source_bucket
    REPORT_BUCKET        = var.report_bucket
    REPORT_READY_TOPIC   = var.report_ready_topic
  }
  report_scheduler_resource   = "projects/${var.project_id}/locations/${var.region}/jobs/${local.report_scheduler_name}"
  watchdog_scheduler_resource = "projects/${var.project_id}/locations/${var.region}/jobs/${local.watchdog_scheduler_name}"
}

resource "google_project_service_identity" "scheduler" {
  provider = google-beta
  project  = var.project_id
  service  = "cloudscheduler.googleapis.com"
}

resource "google_service_account_iam_member" "operator_scheduler_act_as" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.scheduler_service_account}"
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}

resource "google_cloud_run_v2_service" "coordinator" {
  project             = var.project_id
  name                = local.service_name
  location            = var.region
  deletion_protection = !var.allow_destroy
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = { lab = "lab008", component = "coordinator" }

  template {
    service_account                  = var.coordinator_service_account
    timeout                          = "60s"
    max_instance_request_concurrency = 8
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image   = var.image_uri
      command = ["gunicorn"]
      args = [
        "--bind", "0.0.0.0:8080",
        "--workers", "1",
        "--threads", "8",
        "--timeout", "45",
        "app.service:app",
      ]
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      dynamic "env" {
        for_each = merge(local.common_environment, {
          RUN_REGION                  = var.region
          RUN_JOB_NAME                = local.job_name
          REPORT_SCHEDULER_JOB_NAME   = local.report_scheduler_resource
          WATCHDOG_SCHEDULER_JOB_NAME = local.watchdog_scheduler_resource
        })
        content {
          name  = env.key
          value = env.value
        }
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
}

resource "google_cloud_run_v2_service_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.coordinator.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.scheduler_service_account}"
}

resource "google_cloud_run_v2_job" "daily_report" {
  project             = var.project_id
  name                = local.job_name
  location            = var.region
  deletion_protection = !var.allow_destroy
  labels              = { lab = "lab008", component = "daily-report" }

  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = var.worker_service_account
      timeout         = "600s"
      max_retries     = 1
      containers {
        image = var.image_uri
        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
        dynamic "env" {
          for_each = local.common_environment
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job_iam_member" "coordinator_runner" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.daily_report.name
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = "serviceAccount:${var.coordinator_service_account}"
}

resource "google_cloud_run_v2_job_iam_member" "operator_runner" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.daily_report.name
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = var.operator_member
}

resource "google_project_iam_member" "operator_diagnostics" {
  for_each = toset([
    "roles/cloudscheduler.jobRunner",
    "roles/datastore.viewer",
    "roles/logging.viewer",
    "roles/run.viewer",
  ])
  project = var.project_id
  role    = each.value
  member  = var.operator_member
}

resource "google_storage_bucket_iam_member" "operator_source_uploader" {
  bucket = var.source_bucket
  role   = "roles/storage.objectCreator"
  member = var.operator_member
}

resource "google_storage_bucket_iam_member" "operator_report_reader" {
  bucket = var.report_bucket
  role   = "roles/storage.objectViewer"
  member = var.operator_member
}

resource "google_cloud_scheduler_job" "report" {
  project          = var.project_id
  region           = var.region
  name             = local.report_scheduler_name
  description      = "Start the previous Bangkok business date's bounded report job."
  schedule         = "15 1 * * *"
  time_zone        = "Asia/Bangkok"
  paused           = var.pause_schedulers
  attempt_deadline = "30s"

  retry_config {
    retry_count          = 2
    max_retry_duration   = "600s"
    min_backoff_duration = "10s"
    max_backoff_duration = "60s"
    max_doublings        = 2
  }

  http_target {
    uri         = "${google_cloud_run_v2_service.coordinator.uri}/schedule"
    http_method = "POST"
    body        = base64encode("{}")
    headers     = { "Content-Type" = "application/json" }
    oidc_token {
      service_account_email = var.scheduler_service_account
      audience              = google_cloud_run_v2_service.coordinator.uri
    }
  }

  depends_on = [
    google_project_service_identity.scheduler,
    google_service_account_iam_member.operator_scheduler_act_as,
    google_cloud_run_v2_service_iam_member.scheduler_invoker,
  ]
}

resource "google_cloud_scheduler_job" "watchdog" {
  project          = var.project_id
  region           = var.region
  name             = local.watchdog_scheduler_name
  description      = "Verify the previous Bangkok business date's report twice daily."
  schedule         = "0 2,14 * * *"
  time_zone        = "Asia/Bangkok"
  paused           = var.pause_schedulers
  attempt_deadline = "30s"

  retry_config {
    retry_count          = 2
    max_retry_duration   = "600s"
    min_backoff_duration = "10s"
    max_backoff_duration = "60s"
    max_doublings        = 2
  }

  http_target {
    uri         = "${google_cloud_run_v2_service.coordinator.uri}/watchdog"
    http_method = "POST"
    body        = base64encode("{}")
    headers     = { "Content-Type" = "application/json" }
    oidc_token {
      service_account_email = var.scheduler_service_account
      audience              = google_cloud_run_v2_service.coordinator.uri
    }
  }

  depends_on = [
    google_project_service_identity.scheduler,
    google_service_account_iam_member.operator_scheduler_act_as,
    google_cloud_run_v2_service_iam_member.scheduler_invoker,
  ]
}

resource "google_logging_metric" "report_not_ready" {
  project = var.project_id
  name    = "lab008_daily_report_not_ready"
  filter  = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${local.service_name}\" AND jsonPayload.event=\"daily_report_not_ready\""

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Lab 08 daily report not ready"
  }
}

resource "google_monitoring_alert_policy" "report_not_ready" {
  project               = var.project_id
  display_name          = "Lab 08 — Daily report not ready"
  combiner              = "OR"
  enabled               = true
  notification_channels = var.notification_channels

  documentation {
    mime_type = "text/markdown"
    content   = "The scheduled watchdog found a missing, incomplete, or unverifiable report. Check the business date, ledger, report object generation/hash, and Cloud Run execution before starting a bounded backfill."
  }

  conditions {
    display_name = "At least one report-not-ready watchdog event"
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/${google_logging_metric.report_not_ready.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_SUM"
      }
      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "86400s"
  }
}
