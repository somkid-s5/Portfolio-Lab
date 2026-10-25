output "portal_uri" { value = google_cloud_run_v2_service.portal.uri }
output "worker_uri" { value = google_cloud_run_v2_service.worker.uri }
output "trigger_name" { value = google_eventarc_trigger.incoming.name }
