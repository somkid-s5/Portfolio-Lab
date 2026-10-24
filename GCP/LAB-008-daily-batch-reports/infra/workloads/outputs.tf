output "coordinator_service_uri" {
  value       = google_cloud_run_v2_service.coordinator.uri
  description = "IAM-authenticated coordinator HTTPS URI."
}

output "daily_report_job_name" {
  value       = google_cloud_run_v2_job.daily_report.name
  description = "Cloud Run Job resource short name."
}

output "report_scheduler_job_name" {
  value       = google_cloud_scheduler_job.report.name
  description = "Daily report Scheduler job name."
}

output "watchdog_scheduler_job_name" {
  value       = google_cloud_scheduler_job.watchdog.name
  description = "Watchdog Scheduler job name."
}

output "report_not_ready_metric" {
  value       = google_logging_metric.report_not_ready.name
  description = "Log-based metric consumed by the alert policy."
}

output "schedulers_paused" {
  value       = var.pause_schedulers
  description = "Whether both Scheduler triggers remain paused."
}
