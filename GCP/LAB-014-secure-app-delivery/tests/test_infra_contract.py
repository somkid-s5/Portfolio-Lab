from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"


class InfrastructureContractTests(unittest.TestCase):
    def test_wif_is_repository_workflow_branch_and_environment_scoped(self):
        source = (INFRA / "main.tf").read_text(encoding="utf-8")
        for claim in (
            "assertion.repository_id == '1428247317'",
            "assertion.ref == 'refs/heads/main'",
            "assertion.workflow_ref == 'somkid-s5/Portfolio-Lab/.github/workflows/release.yml@refs/heads/main'",
            "assertion.environment in ['gcp-attest', 'gcp-release']",
            "attribute.environment/gcp-attest",
            "attribute.environment/gcp-release",
        ):
            self.assertIn(claim, source)
        self.assertNotIn("service_account_key", source.lower())

    def test_policy_is_explicitly_opt_in_and_restricted_to_attested_images(self):
        variables = (INFRA / "variables.tf").read_text(encoding="utf-8")
        source = (INFRA / "main.tf").read_text(encoding="utf-8")
        self.assertIn("default     = false", variables)
        self.assertIn("count   = var.manage_project_binary_authorization_policy ? 1 : 0", source)
        self.assertIn('evaluation_mode         = "REQUIRE_ATTESTATION"', source)
        self.assertIn("google_binary_authorization_attestor.release.name", source)

    def test_iam_roles_are_split_by_build_attest_release_and_runtime(self):
        source = (INFRA / "main.tf").read_text(encoding="utf-8")
        for value in (
            '"roles/artifactregistry.writer"',
            '"roles/cloudbuild.builds.viewer"',
            '"roles/cloudkms.signerVerifier"',
            '"roles/containeranalysis.occurrences.editor"',
            '"roles/clouddeploy.releaser"',
            '"roles/clouddeploy.jobRunner"',
            '"roles/run.developer"',
            '"roles/run.viewer"',
            '"roles/run.invoker"',
        ):
            self.assertIn(value, source)
        self.assertRegex(source, r'runtime\s*=\s*"Lab 14 Cloud Run runtime identity"')

    def test_trigger_is_optional_and_pins_main_and_lab14_path(self):
        source = (INFRA / "main.tf").read_text(encoding="utf-8")
        self.assertIn('count           = var.cloudbuild_connection_id == "" ? 0 : 1', source)
        self.assertIn('branch = "^main$"', source)
        self.assertIn('GCP/LAB-014-secure-app-delivery/**', source)
        self.assertIn('filename        = "GCP/LAB-014-secure-app-delivery/cloudbuild.yaml"', source)


if __name__ == "__main__":
    unittest.main()
