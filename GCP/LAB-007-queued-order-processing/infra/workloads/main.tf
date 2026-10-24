locals {
  region = "asia-southeast1"
  secret_ids = {
    auth       = "lab007-auth"
    portal     = "lab007-db-portal"
    worker     = "lab007-db-worker"
    dispatcher = "lab007-db-dispatcher"
    bootstrap  = "lab007-db-bootstrap"
  }
  service_names = {
    portal     = "lab007-portal"
    worker     = "lab007-worker"
    dispatcher = "lab007-dispatcher"
  }
  service_config = {
    portal = {
      max_instances = 2
      concurrency   = 4
      timeout       = "30s"
    }
    worker = {
      max_instances = var.worker_max_instances
      concurrency   = 1
      timeout       = "60s"
    }
    dispatcher = {
      max_instances = 1
      concurrency   = 1
      timeout       = "60s"
    }
  }
  mounts = {
    portal = {
      auth = {
        secret     = local.secret_ids.auth
        version    = var.secret_versions.auth
        filename   = "auth.json"
        mount_path = "/secrets/auth"
      }
      db = {
        secret     = local.secret_ids.portal
        version    = var.secret_versions.portal
        filename   = "db.json"
        mount_path = "/secrets/db"
      }
    }
    worker = {
      db = {
        secret     = local.secret_ids.worker
        version    = var.secret_versions.worker
        filename   = "db.json"
        mount_path = "/secrets/db"
      }
    }
    dispatcher = {
      db = {
        secret     = local.secret_ids.dispatcher
        version    = var.secret_versions.dispatcher
        filename   = "db.json"
        mount_path = "/secrets/db"
      }
    }
  }
  pubsub_agent = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
  bootstrap_mounts = {
    bootstrap = {
      secret     = local.secret_ids.bootstrap
      version    = var.secret_versions.bootstrap
      filename   = "db.json"
      mount_path = "/secrets/bootstrap"
    }
    portal = {
      secret     = local.secret_ids.portal
      version    = var.secret_versions.portal
      filename   = "db.json"
      mount_path = "/secrets/portal"
    }
    worker = {
      secret     = local.secret_ids.worker
      version    = var.secret_versions.worker
      filename   = "db.json"
      mount_path = "/secrets/worker"
    }
    dispatcher = {
      secret     = local.secret_ids.dispatcher
      version    = var.secret_versions.dispatcher
      filename   = "db.json"
      mount_path = "/secrets/dispatcher"
    }
  }
}

data "google_project" "current" {
  project_id = var.project_id
}

data "google_compute_network" "lab007" {
  project = var.project_id
  name    = "lab007-vpc"
}

data "google_compute_subnetwork" "run" {
  project = var.project_id
  region  = local.region
  name    = "lab007-run"
}

data "google_sql_database_instance" "orders" {
  project = var.project_id
  name    = "lab007-orders"
}

data "google_service_account" "runtime" {
  for_each   = toset(["portal", "worker", "dispatcher", "bootstrap", "scheduler"])
  project    = var.project_id
  account_id = "lab007-${each.value}"
}

data "google_secret_manager_secret" "lab007" {
  for_each  = local.secret_ids
  project   = var.project_id
  secret_id = each.value
}

resource "google_cloud_run_v2_service" "app" {
  for_each            = local.service_config
  project             = var.project_id
  name                = local.service_names[each.key]
  location            = local.region
  deletion_protection = !var.allow_destroy
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = { lab = "lab007", component = each.key }

  template {
    service_account                  = data.google_service_account.runtime[each.key].email
    timeout                          = each.value.timeout
    max_instance_request_concurrency = each.value.concurrency
    scaling {
      min_instance_count = 0
      max_instance_count = each.value.max_instances
    }
    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = data.google_compute_network.lab007.id
        subnetwork = data.google_compute_subnetwork.run.id
      }
    }
    containers {
      image = var.serving_image
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
        for_each = merge(
          {
            SERVICE_ROLE                 = each.key
            GOOGLE_CLOUD_PROJECT         = var.project_id
            SQL_INSTANCE_CONNECTION_NAME = data.google_sql_database_instance.orders.connection_name
            DB_SECRET_FILE               = "/secrets/db/db.json"
            DB_SECRET_VERSION            = var.secret_versions[each.key]
          },
          each.key == "portal" ? {
            AUTH_FILE           = "/secrets/auth/auth.json"
            AUTH_SECRET_VERSION = var.secret_versions.auth
          } : {}
        )
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "volume_mounts" {
        for_each = local.mounts[each.key]
        content {
          name       = volume_mounts.key
          mount_path = volume_mounts.value.mount_path
        }
      }
      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 3
        http_get {
          path = "/livez"
          port = 8080
        }
      }
    }
    dynamic "volumes" {
      for_each = local.mounts[each.key]
      content {
        name = volumes.key
        secret {
          secret = data.google_secret_manager_secret.lab007[volumes.value.secret == local.secret_ids.auth ? "auth" : each.key].secret_id
          items {
            version = volumes.value.version
            path    = volumes.value.filename
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "portal_public" {
  project  = var.project_id
  location = local.region
  name     = google_cloud_run_v2_service.app["portal"].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "worker_push" {
  project  = var.project_id
  location = local.region
  name     = google_cloud_run_v2_service.app["worker"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${data.google_service_account.runtime["worker"].email}"
}

resource "google_cloud_run_v2_service_iam_member" "dispatcher_scheduler" {
  project  = var.project_id
  location = local.region
  name     = google_cloud_run_v2_service.app["dispatcher"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${data.google_service_account.runtime["scheduler"].email}"
}

resource "google_pubsub_topic" "orders" {
  project = var.project_id
  name    = "lab007-orders"
  message_storage_policy {
    allowed_persistence_regions = [local.region]
  }
}

resource "google_pubsub_topic" "dead" {
  project = var.project_id
  name    = "lab007-orders-dead"
  message_storage_policy {
    allowed_persistence_regions = [local.region]
  }
}

resource "google_pubsub_topic_iam_member" "dead_letter_forwarder" {
  project = var.project_id
  topic   = google_pubsub_topic.dead.name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent
}

resource "google_pubsub_subscription" "orders" {
  project                    = var.project_id
  name                       = "lab007-orders-worker"
  topic                      = google_pubsub_topic.orders.id
  ack_deadline_seconds       = 60
  message_retention_duration = "86400s"
  expiration_policy {
    ttl = ""
  }
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "60s"
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead.id
    max_delivery_attempts = 10
  }
  push_config {
    push_endpoint = "${google_cloud_run_v2_service.app["worker"].uri}/events/orders"
    attributes = {
      "x-goog-version" = "v1"
    }
    oidc_token {
      service_account_email = data.google_service_account.runtime["worker"].email
      audience              = google_cloud_run_v2_service.app["worker"].uri
    }
  }
  depends_on = [
    google_cloud_run_v2_service_iam_member.worker_push,
    google_pubsub_topic_iam_member.dead_letter_forwarder
  ]
}

resource "google_pubsub_subscription_iam_member" "dead_letter_forwarder_ack" {
  project      = var.project_id
  subscription = google_pubsub_subscription.orders.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}

resource "google_pubsub_subscription" "dead_inspect" {
  project                    = var.project_id
  name                       = "lab007-orders-dead-inspect"
  topic                      = google_pubsub_topic.dead.id
  ack_deadline_seconds       = 600
  message_retention_duration = "86400s"
  expiration_policy {
    ttl = ""
  }
}

resource "google_pubsub_subscription_iam_member" "operator" {
  for_each     = var.operator_member == "" ? {} : { operator = var.operator_member }
  project      = var.project_id
  subscription = google_pubsub_subscription.dead_inspect.name
  role         = "roles/pubsub.subscriber"
  member       = each.value
}

resource "google_pubsub_topic_iam_member" "dispatcher_publish" {
  project = var.project_id
  topic   = google_pubsub_topic.orders.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_service_account.runtime["dispatcher"].email}"
}

resource "google_cloud_scheduler_job" "dispatch" {
  project          = var.project_id
  region           = local.region
  name             = "lab007-outbox-dispatch"
  description      = "Bounded one-minute trigger for the transactional outbox dispatcher."
  schedule         = "* * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "60s"
  retry_config {
    retry_count          = 2
    min_backoff_duration = "5s"
    max_backoff_duration = "30s"
    max_doublings        = 2
  }
  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.app["dispatcher"].uri}/internal/outbox/drain"
    body        = base64encode("{}")
    headers = {
      "Content-Type" = "application/json"
    }
    oidc_token {
      service_account_email = data.google_service_account.runtime["scheduler"].email
      audience              = google_cloud_run_v2_service.app["dispatcher"].uri
    }
  }
  depends_on = [google_cloud_run_v2_service_iam_member.dispatcher_scheduler]
}

resource "google_cloud_run_v2_job" "bootstrap" {
  project             = var.project_id
  name                = "lab007-bootstrap"
  location            = local.region
  deletion_protection = !var.allow_destroy
  labels              = { lab = "lab007", component = "bootstrap" }

  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = data.google_service_account.runtime["bootstrap"].email
      max_retries     = 0
      timeout         = "300s"
      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = data.google_compute_network.lab007.id
          subnetwork = data.google_compute_subnetwork.run.id
        }
      }
      containers {
        image = var.bootstrap_image
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
        env {
          name  = "SERVICE_ROLE"
          value = "bootstrap"
        }
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        env {
          name  = "SQL_INSTANCE_CONNECTION_NAME"
          value = data.google_sql_database_instance.orders.connection_name
        }
        env {
          name  = "BOOTSTRAP_SECRET_VERSION"
          value = var.secret_versions.bootstrap
        }
        env {
          name  = "PORTAL_DB_SECRET_VERSION"
          value = var.secret_versions.portal
        }
        env {
          name  = "WORKER_DB_SECRET_VERSION"
          value = var.secret_versions.worker
        }
        env {
          name  = "DISPATCHER_DB_SECRET_VERSION"
          value = var.secret_versions.dispatcher
        }
        dynamic "volume_mounts" {
          for_each = local.bootstrap_mounts
          content {
            name       = volume_mounts.key
            mount_path = volume_mounts.value.mount_path
          }
        }
      }
      dynamic "volumes" {
        for_each = local.bootstrap_mounts
        content {
          name = volumes.key
          secret {
            secret = data.google_secret_manager_secret.lab007[volumes.key].secret_id
            items {
              version = volumes.value.version
              path    = volumes.value.filename
            }
          }
        }
      }
    }
  }
}

