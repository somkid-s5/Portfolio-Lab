from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"


class Lab13TerraformTests(unittest.TestCase):
    def test_private_network_and_three_separate_buckets(self):
        main = (INFRA / "main.tf").read_text(encoding="utf-8")
        self.assertIn('auto_create_subnetworks = false', main)
        self.assertIn('private_ip_google_access = true', main)
        self.assertEqual(main.count('resource "google_storage_bucket"'), 3)
        self.assertIn('public_access_prevention    = "enforced"', main)
        self.assertIn('force_destroy               = false', main)
        self.assertEqual(main.count('retention_duration_seconds = 0'), 3)

    def test_runtime_and_build_iam_are_narrowly_scoped(self):
        main = (INFRA / "main.tf").read_text(encoding="utf-8")
        for expected in (
            'roles/batch.agentReporter', 'roles/logging.logWriter',
            'roles/artifactregistry.reader', 'roles/artifactregistry.writer',
            'roles/storage.objectViewer', 'roles/storage.objectCreator',
            'roles/iam.serviceAccountUser', 'roles/serviceusage.serviceUsageConsumer',
        ):
            self.assertIn(expected, main)
        runtime_grants = re.findall(r'resource "google_storage_bucket_iam_member" "runtime_[^"]+" \{(.*?)\n\}', main, re.S)
        self.assertEqual(len(runtime_grants), 2)
        self.assertTrue(any('google_storage_bucket.input.name' in grant and 'roles/storage.objectViewer' in grant for grant in runtime_grants))
        self.assertIn('"operator_input_creator"', main)
        self.assertIn('bucket = google_storage_bucket.input.name\n  role   = "roles/storage.objectCreator"\n  member = var.operator_member', main)
        self.assertTrue(any('google_storage_bucket.attempt.name' in grant and 'roles/storage.objectCreator' in grant for grant in runtime_grants))
        self.assertNotIn('google_storage_bucket.published.name\n  role   = "roles/storage.objectCreator"\n  member = google_service_account.runtime.member', main)

    def test_private_tenant_variables_and_no_local_state_in_git(self):
        variables = (INFRA / "variables.tf").read_text(encoding="utf-8")
        ignore = (INFRA / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("bucket_prefix", variables)
        self.assertIn("operator_member", variables)
        self.assertIn("*.tfstate", ignore)
        self.assertIn("terraform.tfvars", ignore)
        self.assertIn("work/", ignore)
        self.assertFalse((INFRA / "terraform.tfvars").exists())


if __name__ == "__main__":
    unittest.main()
