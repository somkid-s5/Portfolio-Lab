output "artifact_registry_repository" {
  description = "Repository used by the single-build, digest-pinned release flow."
  value       = google_artifact_registry_repository.apps.id
}
output "github_wif_provider" {
  description = "Provider resource name for GitHub Actions authentication."
  value       = google_iam_workload_identity_pool_provider.github.name
}
output "builder_service_account" {
  value = google_service_account.lab014["builder"].email
}
output "attestation_key_name" {
  value = google_kms_crypto_key.attestation.name
}
output "attestation_keyring_name" {
  value = google_kms_key_ring.attestation.name
}
output "attestor_service_account" {
  value = google_service_account.lab014["attestor"].email
}
output "releaser_service_account" {
  value = google_service_account.lab014["releaser"].email
}
output "clouddeploy_execution_service_accounts" {
  value = { for key, account in local.execution_accounts : key => account }
}
output "cloudbuild_trigger" {
  description = "Null until a GitHub Cloud Build connection ID is supplied and the optional trigger is created."
  value       = try(google_cloudbuild_trigger.main_push[0].trigger_id, null)
}
output "binary_authorization_policy_managed" {
  value = var.manage_project_binary_authorization_policy
}
