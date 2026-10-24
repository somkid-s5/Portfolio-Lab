locals {
  enabled_apis = toset([
    "artifactregistry.googleapis.com",
    "binaryauthorization.googleapis.com",
    "cloudbuild.googleapis.com",
    "clouddeploy.googleapis.com",
    "cloudkms.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "containeranalysis.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
  ])
  service_accounts = {
    builder             = "Lab 14 Cloud Build image builder"
    attestor            = "Lab 14 artifact attestor"
    releaser            = "Lab 14 GitHub release caller"
    renderer            = "Lab 14 Cloud Deploy renderer"
    staging-deployer    = "Lab 14 staging deployer"
    production-deployer = "Lab 14 production deployer"
    verifier            = "Lab 14 Cloud Deploy revision verifier"
    runtime             = "Lab 14 Cloud Run runtime identity"
  }
  project_grants = {
    builder_logs = {
      member = format("serviceAccount:%s", google_service_account.lab014["builder"].email)
      role   = "roles/logging.logWriter"
    }
    attestor_build_viewer = {
      member = format("serviceAccount:%s", google_service_account.lab014["attestor"].email)
      role   = "roles/cloudbuild.builds.viewer"
    }
    attestor_occurrences_editor = {
      member = format("serviceAccount:%s", google_service_account.lab014["attestor"].email)
      role   = "roles/containeranalysis.occurrences.editor"
    }
    releaser = {
      member = format("serviceAccount:%s", google_service_account.lab014["releaser"].email)
      role   = "roles/clouddeploy.releaser"
    }
    renderer_job_runner = {
      member = format("serviceAccount:%s", google_service_account.lab014["renderer"].email)
      role   = "roles/clouddeploy.jobRunner"
    }
    staging_job_runner = {
      member = format("serviceAccount:%s", google_service_account.lab014["staging-deployer"].email)
      role   = "roles/clouddeploy.jobRunner"
    }
    staging_run_developer = {
      member = format("serviceAccount:%s", google_service_account.lab014["staging-deployer"].email)
      role   = "roles/run.developer"
    }
    production_job_runner = {
      member = format("serviceAccount:%s", google_service_account.lab014["production-deployer"].email)
      role   = "roles/clouddeploy.jobRunner"
    }
    production_run_developer = {
      member = format("serviceAccount:%s", google_service_account.lab014["production-deployer"].email)
      role   = "roles/run.developer"
    }
    verifier_job_runner = {
      member = format("serviceAccount:%s", google_service_account.lab014["verifier"].email)
      role   = "roles/clouddeploy.jobRunner"
    }
    verifier_run_viewer = {
      member = format("serviceAccount:%s", google_service_account.lab014["verifier"].email)
      role   = "roles/run.viewer"
    }
    verifier_run_invoker = {
      member = format("serviceAccount:%s", google_service_account.lab014["verifier"].email)
      role   = "roles/run.invoker"
    }
  }
  execution_accounts = {
    renderer            = google_service_account.lab014["renderer"].name
    staging-deployer    = google_service_account.lab014["staging-deployer"].name
    production-deployer = google_service_account.lab014["production-deployer"].name
    verifier            = google_service_account.lab014["verifier"].name
  }
  releaser_act_as_accounts = local.execution_accounts
  runtime_act_as_deployers = toset([
    "staging-deployer",
    "production-deployer",
  ])
  artifact_readers = toset([
    format("serviceAccount:%s", google_service_account.lab014["renderer"].email),
    format("serviceAccount:%s", google_service_account.lab014["staging-deployer"].email),
    format("serviceAccount:%s", google_service_account.lab014["production-deployer"].email),
    format("serviceAccount:%s", google_service_account.lab014["verifier"].email),
  ])
}
data "google_project" "current" {
  project_id = var.project_id
}
resource "google_project_service" "enabled" {
  for_each                   = local.enabled_apis
  project                    = var.project_id
  service                    = each.value
  disable_dependent_services = false
  disable_on_destroy         = false
}
resource "google_service_account" "lab014" {
  for_each     = local.service_accounts
  project      = var.project_id
  account_id   = format("lab014-%s", each.key)
  display_name = each.value
  description  = "Dedicated least-purpose identity for the Lab 14 secure delivery solution."
  depends_on   = [google_project_service.enabled]
}
resource "google_artifact_registry_repository" "apps" {
  project       = var.project_id
  location      = var.region
  repository_id = "lab014-apps"
  description   = "Immutable application images for the Lab 14 delivery pipeline."
  format        = "DOCKER"
  labels        = { lab = "lab014" }
  depends_on    = [google_project_service.enabled]
}
resource "google_artifact_registry_repository_iam_member" "builder_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.apps.location
  repository = google_artifact_registry_repository.apps.repository_id
  role       = "roles/artifactregistry.writer"
  member     = format("serviceAccount:%s", google_service_account.lab014["builder"].email)
}
resource "google_artifact_registry_repository_iam_member" "execution_reader" {
  for_each   = local.artifact_readers
  project    = var.project_id
  location   = google_artifact_registry_repository.apps.location
  repository = google_artifact_registry_repository.apps.repository_id
  role       = "roles/artifactregistry.reader"
  member     = each.value
}
resource "google_project_service_identity" "cloudbuild" {
  provider   = google-beta
  project    = var.project_id
  service    = "cloudbuild.googleapis.com"
  depends_on = [google_project_service.enabled["cloudbuild.googleapis.com"]]
}
resource "google_service_account_iam_member" "cloudbuild_act_as_builder" {
  service_account_id = google_service_account.lab014["builder"].name
  role               = "roles/iam.serviceAccountUser"
  member             = format("serviceAccount:%s", google_project_service_identity.cloudbuild.email)
}
resource "google_cloudbuildv2_repository" "portfolio_lab" {
  count             = var.cloudbuild_connection_id == "" ? 0 : 1
  project           = var.project_id
  location          = var.region
  name              = "lab014-portfolio-lab"
  parent_connection = var.cloudbuild_connection_id
  remote_uri        = var.github_repository_uri
}
resource "google_cloudbuild_trigger" "main_push" {
  count           = var.cloudbuild_connection_id == "" ? 0 : 1
  project         = var.project_id
  location        = var.region
  name            = "lab014-main-push"
  description     = "Build Lab 14 only for trusted pushes to main."
  service_account = google_service_account.lab014["builder"].name
  filename        = "GCP/LAB-014-secure-app-delivery/cloudbuild.yaml"
  included_files = [
    "GCP/LAB-014-secure-app-delivery/app/**",
    "GCP/LAB-014-secure-app-delivery/cloudbuild.yaml",
    "GCP/LAB-014-secure-app-delivery/deploy/**",
    "GCP/LAB-014-secure-app-delivery/skaffold.yaml",
    "GCP/LAB-014-secure-app-delivery/tests/**",
    "GCP/LAB-014-secure-app-delivery/tools/**",
    ".github/workflows/release.yml",
  ]
  repository_event_config {
    repository = google_cloudbuildv2_repository.portfolio_lab[0].id
    push {
      branch = "^main$"
    }
  }
  depends_on = [google_service_account_iam_member.cloudbuild_act_as_builder]
}
resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "lab014-github"
  display_name              = "Lab 14 GitHub Actions"
  description               = "OIDC trust limited to the Lab 14 release workflow on main."
  disabled                  = false
  depends_on                = [google_project_service.enabled["iam.googleapis.com"]]
}
resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "portfolio-lab-main"
  display_name                       = "somkid-s5 Portfolio-Lab main workflow"
  description                        = "Maps repository, ref, workflow and protected GitHub Environment claims."
  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository_id" = "assertion.repository_id"
    "attribute.ref"           = "assertion.ref"
    "attribute.workflow_ref"  = "assertion.workflow_ref"
    "attribute.environment"   = "assertion.environment"
  }
  attribute_condition = "assertion.repository_id == '1428247317' && assertion.ref == 'refs/heads/main' && assertion.workflow_ref == 'somkid-s5/Portfolio-Lab/.github/workflows/release.yml@refs/heads/main' && assertion.environment in ['gcp-attest', 'gcp-release']"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}
resource "google_service_account_iam_member" "github_attestor" {
  service_account_id = google_service_account.lab014["attestor"].name
  role               = "roles/iam.workloadIdentityUser"
  member = format(
    "principalSet://iam.googleapis.com/projects/%s/locations/global/workloadIdentityPools/%s/attribute.environment/gcp-attest",
    data.google_project.current.number,
    google_iam_workload_identity_pool.github.workload_identity_pool_id,
  )
  depends_on = [google_iam_workload_identity_pool_provider.github]
}
resource "google_service_account_iam_member" "github_releaser" {
  service_account_id = google_service_account.lab014["releaser"].name
  role               = "roles/iam.workloadIdentityUser"
  member = format(
    "principalSet://iam.googleapis.com/projects/%s/locations/global/workloadIdentityPools/%s/attribute.environment/gcp-release",
    data.google_project.current.number,
    google_iam_workload_identity_pool.github.workload_identity_pool_id,
  )
  depends_on = [google_iam_workload_identity_pool_provider.github]
}
resource "google_kms_key_ring" "attestation" {
  project    = var.project_id
  name       = "lab014-attestation"
  location   = var.region
  depends_on = [google_project_service.enabled["cloudkms.googleapis.com"]]
}
resource "google_kms_crypto_key" "attestation" {
  name                       = "lab014-release-signing"
  key_ring                   = google_kms_key_ring.attestation.id
  purpose                    = "ASYMMETRIC_SIGN"
  destroy_scheduled_duration = "2592000s"
  version_template {
    algorithm = "RSA_SIGN_PSS_2048_SHA256"
  }
}
data "google_kms_crypto_key_version" "attestation" {
  crypto_key = google_kms_crypto_key.attestation.id
}
resource "google_container_analysis_note" "attestor" {
  project = var.project_id
  name    = "lab014-release-attestor-note"
  attestation_authority {
    hint {
      human_readable_name = "Lab 14 Cloud Build release attestor"
    }
  }
  depends_on = [google_project_service.enabled["containeranalysis.googleapis.com"]]
}
resource "google_binary_authorization_attestor" "release" {
  project     = var.project_id
  name        = "lab014-release-attestor"
  description = "Attests only the exact digest of a verified Lab 14 Cloud Build result."
  attestation_authority_note {
    note_reference = google_container_analysis_note.attestor.name
    public_keys {
      id = data.google_kms_crypto_key_version.attestation.id
      pkix_public_key {
        public_key_pem      = data.google_kms_crypto_key_version.attestation.public_key[0].pem
        signature_algorithm = data.google_kms_crypto_key_version.attestation.public_key[0].algorithm
      }
    }
  }
}
resource "google_kms_crypto_key_iam_member" "attestor_signer" {
  crypto_key_id = google_kms_crypto_key.attestation.id
  role          = "roles/cloudkms.signerVerifier"
  member        = format("serviceAccount:%s", google_service_account.lab014["attestor"].email)
}
resource "google_container_analysis_note_iam_member" "attestor_attacher" {
  project = var.project_id
  note    = google_container_analysis_note.attestor.name
  role    = "roles/containeranalysis.notes.attacher"
  member  = format("serviceAccount:%s", google_service_account.lab014["attestor"].email)
}
resource "google_project_iam_member" "lab014" {
  for_each = local.project_grants
  project  = var.project_id
  role     = each.value.role
  member   = each.value.member
}
resource "google_container_analysis_note_iam_member" "binauthz_delegate_reader" {
  project = var.project_id
  note    = google_container_analysis_note.attestor.name
  role    = "roles/containeranalysis.notes.occurrences.viewer"
  member = format(
    "serviceAccount:%s",
    google_binary_authorization_attestor.release.attestation_authority_note[0].delegation_service_account_email,
  )
}
resource "google_binary_authorization_policy" "project" {
  count   = var.manage_project_binary_authorization_policy ? 1 : 0
  project = var.project_id
  default_admission_rule {
    evaluation_mode         = "REQUIRE_ATTESTATION"
    enforcement_mode        = "ENFORCED_BLOCK_AND_AUDIT_LOG"
    require_attestations_by = [google_binary_authorization_attestor.release.name]
  }
  depends_on = [
    google_container_analysis_note_iam_member.binauthz_delegate_reader,
    google_project_iam_member.lab014,
  ]
}
resource "google_project_service_identity" "clouddeploy" {
  provider   = google-beta
  project    = var.project_id
  service    = "clouddeploy.googleapis.com"
  depends_on = [google_project_service.enabled["clouddeploy.googleapis.com"]]
}
resource "google_service_account_iam_member" "clouddeploy_execution" {
  for_each           = local.execution_accounts
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = format("serviceAccount:%s", google_project_service_identity.clouddeploy.email)
}
resource "google_service_account_iam_member" "releaser_act_as" {
  for_each           = local.releaser_act_as_accounts
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = format("serviceAccount:%s", google_service_account.lab014["releaser"].email)
}
resource "google_service_account_iam_member" "runtime_act_as" {
  for_each           = local.runtime_act_as_deployers
  service_account_id = google_service_account.lab014["runtime"].name
  role               = "roles/iam.serviceAccountUser"
  member             = format("serviceAccount:%s", google_service_account.lab014[each.value].email)
}
resource "google_project_iam_member" "production_approver" {
  count   = var.approver_principal == "" ? 0 : 1
  project = var.project_id
  role    = "roles/clouddeploy.approver"
  member  = var.approver_principal
}
