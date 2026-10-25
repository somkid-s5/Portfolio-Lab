terraform {
  required_version = ">= 1.9.8, < 2.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 7.29.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "= 7.29.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  description = "Existing Lab 19 project used by the Foundation stack."
  type        = string
}

variable "region" {
  description = "Region where the Foundation stack created Cloud Run and Cloud SQL."
  type        = string
  default     = "asia-southeast1"
}

variable "image_digest" {
  description = "Immutable image digest from Artifact Registry, for example sha256:<64 lowercase hex characters>."
  type        = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be the sha256 digest returned by the image push step; do not use a mutable tag."
  }
}

variable "operator_member" {
  description = "IAM member allowed to invoke the Task API and redrive the DLQ."
  type        = string
}

variable "alert_email" {
  description = "Email address for the Lab alert channel. Keep tfvars and state private."
  type        = string
  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.alert_email))
    error_message = "alert_email must be a valid email address used only in your private tfvars file."
  }
}

variable "api_fault_mode" {
  description = "Temporary lab control: none, 5xx, or slow. Keep none outside fault drills."
  type        = string
  default     = "none"
  validation {
    condition     = contains(["none", "5xx", "slow"], var.api_fault_mode)
    error_message = "api_fault_mode must be none, 5xx, or slow."
  }
}

variable "worker_fault_mode" {
  description = "Temporary lab control: none or 503. Keep none outside the worker retry drill."
  type        = string
  default     = "none"
  validation {
    condition     = contains(["none", "503", "slow"], var.worker_fault_mode)
    error_message = "worker_fault_mode must be none, 503, or slow."
  }
}

variable "worker_delay_ms" {
  description = "Bounded worker delay used only when worker_fault_mode is slow."
  type        = number
  default     = 0
  validation {
    condition     = var.worker_delay_ms >= 0 && var.worker_delay_ms <= 10000
    error_message = "worker_delay_ms must be between 0 and 10000."
  }
}

locals {
  image = format(
    "%s-docker.pkg.dev/%s/lab19-apps/lab19-service@%s",
    var.region,
    var.project_id,
    var.image_digest,
  )
  api_name         = "lab19-task-api"
  worker_name      = "lab19-task-worker"
  subscription     = "lab19-task-push"
  dlq_subscription = "lab19-task-dlq-reader"
  db_instance      = "lab19-postgres"
  db_name          = "lab19"
  network_name     = "lab19-vpc"
  subnet_name      = "lab19-run-egress"
  api_sa           = format("lab19-api@%s.iam.gserviceaccount.com", var.project_id)
  worker_sa        = format("lab19-worker@%s.iam.gserviceaccount.com", var.project_id)
  push_sa          = format("lab19-push@%s.iam.gserviceaccount.com", var.project_id)
  monitor_metric   = "logging.googleapis.com/user/lab19_eligible_requests"
}

data "google_project" "current" {
  project_id = var.project_id
}

data "google_compute_network" "lab" {
  name = local.network_name
}

data "google_compute_subnetwork" "run_egress" {
  name   = local.subnet_name
  region = var.region
}

resource "google_sql_user" "api" {
  project        = var.project_id
  name           = trimsuffix(local.api_sa, ".gserviceaccount.com")
  instance       = local.db_instance
  type           = "CLOUD_IAM_SERVICE_ACCOUNT"
  database_roles = ["lab19_api_role"]
}

resource "google_sql_user" "worker" {
  project        = var.project_id
  name           = trimsuffix(local.worker_sa, ".gserviceaccount.com")
  instance       = local.db_instance
  type           = "CLOUD_IAM_SERVICE_ACCOUNT"
  database_roles = ["lab19_worker_role"]
}

resource "google_cloud_run_v2_service" "api" {
  name                 = local.api_name
  location             = var.region
  project              = var.project_id
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = false
  deletion_protection  = false

  template {
    service_account                  = local.api_sa
    max_instance_request_concurrency = 10
    timeout                          = "30s"

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = local.image

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
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "INSTANCE_CONNECTION_NAME"
        value = format("%s:%s:%s", var.project_id, var.region, local.db_instance)
      }
      env {
        name  = "DB_NAME"
        value = local.db_name
      }
      env {
        name  = "DB_IAM_USER"
        value = trimsuffix(local.api_sa, ".gserviceaccount.com")
      }
      env {
        name  = "PUBSUB_TOPIC"
        value = format("projects/%s/topics/lab19-tasks", var.project_id)
      }
      env {
        name  = "API_FAULT_MODE"
        value = var.api_fault_mode
      }
      env {
        name  = "API_FAULT_DELAY_MS"
        value = "1200"
      }
    }

    vpc_access {
      network_interfaces {
        network    = data.google_compute_network.lab.id
        subnetwork = data.google_compute_subnetwork.run_egress.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
  }

  depends_on = [
    google_sql_user.api,
  ]
}

resource "google_cloud_run_v2_service" "worker" {
  name                 = local.worker_name
  location             = var.region
  project              = var.project_id
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = false
  deletion_protection  = false

  template {
    service_account                  = local.worker_sa
    max_instance_request_concurrency = 1
    timeout                          = "30s"

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = local.image

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
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "INSTANCE_CONNECTION_NAME"
        value = format("%s:%s:%s", var.project_id, var.region, local.db_instance)
      }
      env {
        name  = "DB_NAME"
        value = local.db_name
      }
      env {
        name  = "DB_IAM_USER"
        value = trimsuffix(local.worker_sa, ".gserviceaccount.com")
      }
      env {
        name  = "WORKER_FAULT_MODE"
        value = var.worker_fault_mode
      }
      env {
        name  = "WORKER_DELAY_MS"
        value = tostring(var.worker_delay_ms)
      }
    }

    vpc_access {
      network_interfaces {
        network    = data.google_compute_network.lab.id
        subnetwork = data.google_compute_subnetwork.run_egress.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
  }

  depends_on = [
    google_sql_user.worker,
  ]
}

resource "google_project_service_identity" "pubsub" {
  provider = google-beta
  project  = var.project_id
  service  = "pubsub.googleapis.com"
}

resource "google_project_service_identity" "monitoring" {
  provider = google-beta
  project  = var.project_id
  service  = "monitoring.googleapis.com"
}

resource "google_service_account_iam_member" "pubsub_mints_push_token" {
  service_account_id = format("projects/%s/serviceAccounts/%s", var.project_id, local.push_sa)
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = google_project_service_identity.pubsub.member
}

resource "google_cloud_run_v2_service_iam_member" "operator_invokes_api" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = var.operator_member
}

resource "google_cloud_run_v2_service_iam_member" "push_invokes_worker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = format("serviceAccount:%s", local.push_sa)
}

resource "google_cloud_run_v2_service_iam_member" "uptime_invokes_api" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = google_project_service_identity.monitoring.member
}

resource "google_pubsub_subscription" "task_push" {
  name                       = local.subscription
  project                    = var.project_id
  topic                      = format("projects/%s/topics/lab19-tasks", var.project_id)
  ack_deadline_seconds       = 30
  message_retention_duration = "86400s"
  labels                     = { lab = "lab19" }

  push_config {
    push_endpoint = format("%s/events", google_cloud_run_v2_service.worker.uri)

    oidc_token {
      service_account_email = local.push_sa
      audience              = google_cloud_run_v2_service.worker.uri
    }
  }

  dead_letter_policy {
    dead_letter_topic     = format("projects/%s/topics/lab19-tasks-dlq", var.project_id)
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "60s"
  }

  depends_on = [
    google_service_account_iam_member.pubsub_mints_push_token,
    google_cloud_run_v2_service_iam_member.push_invokes_worker,
  ]
}

resource "google_pubsub_subscription" "dead_letter_reader" {
  name                       = local.dlq_subscription
  project                    = var.project_id
  topic                      = format("projects/%s/topics/lab19-tasks-dlq", var.project_id)
  ack_deadline_seconds       = 30
  message_retention_duration = "604800s"
  labels                     = { lab = "lab19" }
}

resource "google_pubsub_topic_iam_member" "pubsub_agent_publishes_dlq" {
  project = var.project_id
  topic   = "lab19-tasks-dlq"
  role    = "roles/pubsub.publisher"
  member  = google_project_service_identity.pubsub.member
}

resource "google_pubsub_subscription_iam_member" "pubsub_agent_reads_source" {
  project      = var.project_id
  subscription = google_pubsub_subscription.task_push.name
  role         = "roles/pubsub.subscriber"
  member       = google_project_service_identity.pubsub.member
}

resource "google_pubsub_subscription_iam_member" "operator_reads_dlq" {
  project      = var.project_id
  subscription = google_pubsub_subscription.dead_letter_reader.name
  role         = "roles/pubsub.subscriber"
  member       = var.operator_member
}

resource "google_pubsub_topic_iam_member" "operator_redrives_dlq" {
  project = var.project_id
  topic   = "lab19-tasks"
  role    = "roles/pubsub.publisher"
  member  = var.operator_member
}

resource "google_logging_metric" "eligible_requests" {
  project = var.project_id
  name    = "lab19_eligible_requests"
  filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    format("resource.labels.service_name=\"%s\"", local.api_name),
    "jsonPayload.event=\"business_request\"",
    "jsonPayload.eligible=true",
  ])

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Lab 19 eligible API request outcomes"

    labels {
      key         = "outcome"
      value_type  = "STRING"
      description = "good or bad result for an eligible API request"
    }
  }

  label_extractors = {
    outcome = "EXTRACT(jsonPayload.outcome)"
  }
}

resource "google_logging_metric" "request_duration" {
  project = var.project_id
  name    = "lab19_request_duration_ms"
  filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    format("resource.labels.service_name=\"%s\"", local.api_name),
    "jsonPayload.event=\"business_request\"",
    "jsonPayload.eligible=true",
  ])

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "DISTRIBUTION"
    unit         = "ms"
    display_name = "Lab 19 eligible API request duration"
  }

  value_extractor = "EXTRACT(jsonPayload.duration_ms)"
  bucket_options {
    explicit_buckets {
      bounds = [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 5000]
    }
  }
}

resource "google_logging_metric" "worker_failures" {
  project = var.project_id
  name    = "lab19_worker_failures"
  filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    format("resource.labels.service_name=\"%s\"", local.worker_name),
    "jsonPayload.event=\"worker_task\"",
    "jsonPayload.outcome=\"retryable_error\"",
  ])
}

resource "google_monitoring_service" "task_api" {
  project      = var.project_id
  service_id   = "lab19-task-api"
  display_name = "Lab 19 Task API"

  basic_service {
    service_type = "CLOUD_RUN"
    service_labels = {
      service_name = google_cloud_run_v2_service.api.name
      location     = var.region
    }
  }
}

resource "google_monitoring_slo" "availability" {
  project             = var.project_id
  service             = google_monitoring_service.task_api.service_id
  slo_id              = "availability-7d"
  display_name        = "Task API eligible request availability"
  goal                = 0.995
  rolling_period_days = 7

  request_based_sli {
    good_total_ratio {
      good_service_filter  = "metric.type = \"logging.googleapis.com/user/lab19_eligible_requests\" AND metric.label.outcome = \"good\""
      total_service_filter = "metric.type = \"logging.googleapis.com/user/lab19_eligible_requests\""
    }
  }

  depends_on = [google_logging_metric.eligible_requests]
}

resource "google_monitoring_slo" "latency" {
  project             = var.project_id
  service             = google_monitoring_service.task_api.service_id
  slo_id              = "latency-7d"
  display_name        = "95 percent of eligible Task API requests under one second"
  goal                = 0.95
  rolling_period_days = 7

  request_based_sli {
    distribution_cut {
      distribution_filter = "metric.type = \"logging.googleapis.com/user/lab19_request_duration_ms\""
      range {
        min = 0
        max = 1000
      }
    }
  }

  depends_on = [google_logging_metric.request_duration]
}

resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "Lab 19 On-call email"
  type         = "email"
  enabled      = true
  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "availability_fast_burn" {
  project               = var.project_id
  display_name          = "Lab 19 · Task API fast SLO burn"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.name]
  enabled               = true
  user_labels           = { lab = "lab19", severity = "page" }

  conditions {
    display_name = "Availability burn rate above 10x for 60m"
    condition_threshold {
      filter          = format("select_slo_burn_rate(\"%s\", \"60m\")", google_monitoring_slo.availability.name)
      comparison      = "COMPARISON_GT"
      threshold_value = 10
      duration        = "0s"
      trigger {
        count = 1
      }
    }
  }

  documentation {
    mime_type = "text/markdown"
    content   = "Check user impact, API errors, Pub/Sub backlog, Worker, and Cloud SQL using the Lab 19 runbook. Do not resolve until recovery is verified."
  }
}

resource "google_monitoring_alert_policy" "availability_slow_burn" {
  project               = var.project_id
  display_name          = "Lab 19 · Task API slow SLO burn"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.name]
  enabled               = true
  user_labels           = { lab = "lab19", severity = "ticket" }

  conditions {
    display_name = "Availability burn rate above 2x for 24h"
    condition_threshold {
      filter          = format("select_slo_burn_rate(\"%s\", \"24h\")", google_monitoring_slo.availability.name)
      comparison      = "COMPARISON_GT"
      threshold_value = 2
      duration        = "0s"
      trigger {
        count = 1
      }
    }
  }
}

resource "google_monitoring_alert_policy" "queue_oldest_message" {
  project               = var.project_id
  display_name          = "Lab 19 · Task queue oldest message"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.name]
  enabled               = true
  user_labels           = { lab = "lab19", severity = "ticket" }

  conditions {
    display_name = "Oldest unacked message exceeds five minutes"
    condition_threshold {
      filter          = "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age_by_region\" AND resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"lab19-task-push\""
      comparison      = "COMPARISON_GT"
      threshold_value = 300
      duration        = "300s"
      aggregations {
        alignment_period   = "120s"
        per_series_aligner = "ALIGN_MAX"
      }
      trigger {
        count = 1
      }
    }
  }
}

resource "google_monitoring_alert_policy" "worker_failures" {
  project               = var.project_id
  display_name          = "Lab 19 · Repeated Worker push failures"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.name]
  enabled               = true
  user_labels           = { lab = "lab19", severity = "ticket" }

  conditions {
    display_name = "At least five retryable Worker failures in ten minutes"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/lab19_worker_failures\""
      comparison      = "COMPARISON_GT"
      threshold_value = 4
      duration        = "600s"
      aggregations {
        alignment_period   = "600s"
        per_series_aligner = "ALIGN_SUM"
      }
      trigger {
        count = 1
      }
    }
  }

  depends_on = [google_logging_metric.worker_failures]
}

resource "google_monitoring_alert_policy" "cloud_sql_cpu" {
  project               = var.project_id
  display_name          = "Lab 19 · Cloud SQL CPU saturation"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.name]
  enabled               = true
  user_labels           = { lab = "lab19", severity = "ticket" }

  conditions {
    display_name = "Cloud SQL CPU over 85 percent for five minutes"
    condition_threshold {
      filter = format(
        "metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\" AND resource.type=\"cloudsql_database\" AND resource.labels.database_id=\"%s:%s:%s\"",
        var.project_id,
        var.region,
        local.db_instance,
      )
      comparison      = "COMPARISON_GT"
      threshold_value = 0.85
      duration        = "300s"
      aggregations {
        alignment_period   = "120s"
        per_series_aligner = "ALIGN_MAX"
      }
      trigger {
        count = 1
      }
    }
  }
}

resource "google_monitoring_uptime_check_config" "api_health" {
  project          = var.project_id
  display_name     = "Lab 19 · Authenticated Task API health"
  timeout          = "10s"
  period           = "60s"
  selected_regions = ["ASIA_PACIFIC"]

  http_check {
    path         = "/healthz"
    port         = 443
    use_ssl      = true
    validate_ssl = true
    service_agent_authentication {
      type = "OIDC_TOKEN"
    }
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = replace(google_cloud_run_v2_service.api.uri, "https://", "")
    }
  }

  depends_on = [google_cloud_run_v2_service_iam_member.uptime_invokes_api]
}

resource "google_monitoring_dashboard" "service" {
  project = var.project_id
  dashboard_json = jsonencode({
    displayName = "Lab 19 · Service SLO and operations"
    gridLayout = {
      columns = 2
      widgets = [
        {
          title = "Eligible API outcomes"
          xyChart = {
            dataSets = [{
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/lab19_eligible_requests\""
                  aggregation = {
                    alignmentPeriod  = "60s"
                    perSeriesAligner = "ALIGN_RATE"
                  }
                }
              }
            }]
          }
        },
        {
          title = "Eligible API latency · p95"
          xyChart = {
            dataSets = [{
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/lab19_request_duration_ms\""
                  aggregation = {
                    alignmentPeriod  = "60s"
                    perSeriesAligner = "ALIGN_PERCENTILE_95"
                  }
                }
              }
            }]
          }
        },
        {
          title = "Pub/Sub oldest unacknowledged message by region"
          xyChart = {
            dataSets = [{
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age_by_region\" AND resource.labels.subscription_id=\"lab19-task-push\""
                  aggregation = {
                    alignmentPeriod  = "120s"
                    perSeriesAligner = "ALIGN_MAX"
                  }
                }
              }
            }]
          }
        },
        {
          title = "Cloud SQL CPU utilization"
          xyChart = {
            dataSets = [{
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = format("metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\" AND resource.labels.database_id=\"%s:%s:%s\"", var.project_id, var.region, local.db_instance)
                  aggregation = {
                    alignmentPeriod  = "120s"
                    perSeriesAligner = "ALIGN_MAX"
                  }
                }
              }
            }]
          }
        }
      ]
    }
  })
}

output "api_uri" {
  value       = google_cloud_run_v2_service.api.uri
  description = "Authenticated endpoint for Task API requests."
}

output "worker_uri" {
  value       = google_cloud_run_v2_service.worker.uri
  description = "Authenticated Pub/Sub push endpoint; do not grant allUsers."
}

output "push_subscription" {
  value = google_pubsub_subscription.task_push.name
}

output "dead_letter_subscription" {
  value = google_pubsub_subscription.dead_letter_reader.name
}

output "availability_slo_name" {
  value = google_monitoring_slo.availability.name
}

output "latency_slo_name" {
  value = google_monitoring_slo.latency.name
}
