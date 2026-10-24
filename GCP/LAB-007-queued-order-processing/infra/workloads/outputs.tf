output "portal_url" {
  value = google_cloud_run_v2_service.app["portal"].uri
}

output "worker_url" {
  value = google_cloud_run_v2_service.app["worker"].uri
}

output "dispatcher_url" {
  value = google_cloud_run_v2_service.app["dispatcher"].uri
}

output "bootstrap_job" {
  value = google_cloud_run_v2_job.bootstrap.name
}

output "source_subscription" {
  value = google_pubsub_subscription.orders.name
}

output "dead_letter_subscription" {
  value = google_pubsub_subscription.dead_inspect.name
}
