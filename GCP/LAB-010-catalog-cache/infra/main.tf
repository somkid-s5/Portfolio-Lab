locals {
  enabled_apis = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "redis.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "serviceusage.googleapis.com",
  ])

  runtime_accounts = {
    reader   = "catalog-reader"
    operator = "catalog-operator"
    migrator = "catalog-migrator"
    builder  = "catalog-builder"
  }

  database_accounts = toset(["reader", "operator", "migrator"])

  runtime_secret_access = {
    reader_auth   = { identity = "reader", secret = "auth" }
    reader_ca     = { identity = "reader", secret = "ca" }
    operator_auth = { identity = "operator", secret = "auth" }
    operator_ca   = { identity = "operator", secret = "ca" }
  }

  sql_db_usernames = {
    for role in local.database_accounts :
    role => trimsuffix(google_service_account.runtime[role].email, ".gserviceaccount.com")
  }

  run_roles = {
    public = {
      app_role           = "public"
      identity           = "reader"
      max_instance_count = 2
    }
    operator = {
      app_role           = "admin"
      identity           = "operator"
      max_instance_count = 1
    }
  }
}

resource "google_project_service" "api" {
  for_each           = local.enabled_apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "lab" {
  project                 = var.project_id
  name                    = "lab010-vpc"
  auto_create_subnetworks = false
  routing_mode            = "GLOBAL"

  depends_on = [google_project_service.api]
}

resource "google_compute_subnetwork" "run" {
  project                  = var.project_id
  name                     = "lab010-run-snet"
  region                   = var.region
  network                  = google_compute_network.lab.id
  ip_cidr_range            = "10.10.0.0/26"
  private_ip_google_access = true
}

resource "google_compute_global_address" "private_services" {
  project       = var.project_id
  name          = "lab010-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.lab.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.lab.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]

  depends_on = [google_project_service.api]
}

resource "google_sql_database_instance" "catalog" {
  project             = var.project_id
  name                = "lab010-catalog-db"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = !var.allow_destroy

  settings {
    tier                        = "db-custom-1-3840"
    edition                     = "ENTERPRISE"
    disk_type                   = "PD_SSD"
    disk_size                   = 10
    disk_autoresize             = false
    availability_type           = "ZONAL"
    deletion_protection_enabled = !var.allow_destroy

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.lab.id
      enable_private_path_for_google_cloud_services = true
    }

    backup_configuration {
      enabled = false
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }
  }

  depends_on = [google_service_networking_connection.private_services]
}

resource "google_sql_database" "catalog" {
  project  = var.project_id
  name     = "catalog"
  instance = google_sql_database_instance.catalog.name
}

resource "google_redis_instance" "catalog" {
  project                 = var.project_id
  name                    = "lab010-catalog-cache"
  region                  = var.region
  tier                    = "BASIC"
  memory_size_gb          = 1
  redis_version           = "REDIS_7_0"
  connect_mode            = "PRIVATE_SERVICE_ACCESS"
  authorized_network      = google_compute_network.lab.id
  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"
  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_service_networking_connection.private_services]
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "lab010-images"
  description   = "Private container images for the Catalog Cache solution lab."
  format        = "DOCKER"
  labels        = { lab = "lab010" }

  depends_on = [google_project_service.api]
}

resource "google_service_account" "runtime" {
  for_each     = local.runtime_accounts
  project      = var.project_id
  account_id   = "lab010-${each.value}"
  display_name = "Lab 10 ${each.value} identity"

  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret" "redis_auth" {
  project   = var.project_id
  secret_id = "lab010-redis-auth"

  replication {
    auto {}
  }

  labels = {
    lab       = "lab010"
    component = "redis-auth"
  }

  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret" "redis_ca" {
  project   = var.project_id
  secret_id = "lab010-redis-ca"

  replication {
    auto {}
  }

  labels = {
    lab       = "lab010"
    component = "redis-ca"
  }

  depends_on = [google_project_service.api]
}

resource "google_project_iam_member" "sql_client" {
  for_each = local.database_accounts
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = google_service_account.runtime[each.value].member
}

resource "google_project_iam_member" "sql_instance_user" {
  for_each = local.database_accounts
  project  = var.project_id
  role     = "roles/cloudsql.instanceUser"
  member   = google_service_account.runtime[each.value].member
}

resource "google_sql_user" "iam" {
  for_each        = local.database_accounts
  project         = var.project_id
  instance        = google_sql_database_instance.catalog.name
  name            = local.sql_db_usernames[each.key]
  type            = "CLOUD_IAM_SERVICE_ACCOUNT"
  deletion_policy = "ABANDON"
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = local.runtime_secret_access
  project   = var.project_id
  secret_id = each.value.secret == "auth" ? google_secret_manager_secret.redis_auth.secret_id : google_secret_manager_secret.redis_ca.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.runtime[each.value.identity].member
}

resource "google_artifact_registry_repository_iam_member" "builder_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.runtime["builder"].member
}

resource "google_project_iam_member" "builder_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = google_service_account.runtime["builder"].member
}

resource "google_project_iam_member" "operator_build_submit" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.editor"
  member  = var.operator_member
}

resource "google_service_account_iam_member" "operator_builder_act_as" {
  service_account_id = google_service_account.runtime["builder"].name
  role               = "roles/iam.serviceAccountUser"
  member             = var.operator_member
}

resource "google_project_iam_member" "runtime_logs_viewer" {
  project = var.project_id
  role    = "roles/logging.viewer"
  member  = var.operator_member
}

resource "google_project_iam_member" "runtime_metrics_viewer" {
  project = var.project_id
  role    = "roles/monitoring.viewer"
  member  = var.operator_member
}

resource "google_cloud_run_v2_service" "catalog" {
  for_each            = var.enable_workloads ? local.run_roles : {}
  project             = var.project_id
  name                = each.key == "public" ? "lab010-catalog-public" : "lab010-catalog-operator"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = !var.allow_destroy

  template {
    service_account                  = google_service_account.runtime[each.value.identity].email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = 0
      max_instance_count = each.value.max_instance_count
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"

      network_interfaces {
        network    = google_compute_network.lab.id
        subnetwork = google_compute_subnetwork.run.id
      }
    }

    containers {
      image = var.image_uri

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "APP_ROLE"
        value = each.value.app_role
      }
      env {
        name  = "INSTANCE_CONNECTION_NAME"
        value = google_sql_database_instance.catalog.connection_name
      }
      env {
        name  = "DB_NAME"
        value = google_sql_database.catalog.name
      }
      env {
        name  = "DB_IAM_USER"
        value = local.sql_db_usernames[each.value.identity]
      }
      env {
        name  = "REDIS_HOST"
        value = google_redis_instance.catalog.host
      }
      env {
        name  = "REDIS_PORT"
        value = "6378"
      }
      env {
        name  = "REDIS_AUTH_FILE"
        value = "/var/run/lab10-secrets/auth/auth"
      }
      env {
        name  = "REDIS_CA_FILE"
        value = "/var/run/lab10-secrets/ca/ca.pem"
      }
      env {
        name  = "CATEGORY_LIST_TTL_SECONDS"
        value = tostring(var.category_list_ttl_seconds)
      }

      volume_mounts {
        name       = "redis-auth"
        mount_path = "/var/run/lab10-secrets/auth"
      }
      volume_mounts {
        name       = "redis-ca"
        mount_path = "/var/run/lab10-secrets/ca"
      }

      startup_probe {
        initial_delay_seconds = 5
        period_seconds        = 10
        timeout_seconds       = 3
        failure_threshold     = 6

        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }

    volumes {
      name = "redis-auth"

      secret {
        secret = google_secret_manager_secret.redis_auth.secret_id

        items {
          version = var.redis_auth_version
          path    = "auth"
        }
      }
    }

    volumes {
      name = "redis-ca"

      secret {
        secret = google_secret_manager_secret.redis_ca.secret_id

        items {
          version = var.redis_ca_version
          path    = "ca.pem"
        }
      }
    }
  }

  depends_on = [
    google_sql_user.iam,
    google_project_iam_member.sql_client,
    google_project_iam_member.sql_instance_user,
    google_secret_manager_secret_iam_member.runtime,
    google_service_networking_connection.private_services,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.enable_workloads ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.catalog["public"].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "operator_invoker" {
  count    = var.enable_workloads ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.catalog["operator"].name
  role     = "roles/run.invoker"
  member   = var.operator_member
}

resource "google_cloud_run_v2_job" "migrate" {
  count               = var.enable_workloads ? 1 : 0
  project             = var.project_id
  name                = "lab010-catalog-migrate"
  location            = var.region
  deletion_protection = !var.allow_destroy

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.runtime["migrator"].email
      max_retries     = 0
      timeout         = "600s"

      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"

        network_interfaces {
          network    = google_compute_network.lab.id
          subnetwork = google_compute_subnetwork.run.id
        }
      }

      containers {
        image = var.image_uri

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        env {
          name  = "APP_ROLE"
          value = "migrate"
        }
        env {
          name  = "INSTANCE_CONNECTION_NAME"
          value = google_sql_database_instance.catalog.connection_name
        }
        env {
          name  = "DB_NAME"
          value = google_sql_database.catalog.name
        }
        env {
          name  = "DB_IAM_USER"
          value = local.sql_db_usernames["migrator"]
        }
        env {
          name  = "DB_READER_USER"
          value = local.sql_db_usernames["reader"]
        }
        env {
          name  = "DB_OPERATOR_USER"
          value = local.sql_db_usernames["operator"]
        }
      }
    }
  }

  depends_on = [
    google_sql_user.iam,
    google_project_iam_member.sql_client,
    google_project_iam_member.sql_instance_user,
    google_service_networking_connection.private_services,
  ]
}

resource "google_cloud_run_v2_job_iam_member" "operator_run_migration" {
  count    = var.enable_workloads ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.migrate[0].name
  role     = "roles/run.invoker"
  member   = var.operator_member
}
