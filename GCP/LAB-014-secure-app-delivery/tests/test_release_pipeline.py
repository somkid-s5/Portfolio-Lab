from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_pipeline", ROOT / "tools" / "release.py")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64
PROJECT = "lab-project-123"
TRIGGER = "abcdef123456"
BUILDER = f"lab014-builder@{PROJECT}.iam.gserviceaccount.com"


def build_record(**changes):
    value = {
        "id": "build-12345678",
        "projectId": PROJECT,
        "buildTriggerId": TRIGGER,
        "status": "SUCCESS",
        "serviceAccount": f"projects/{PROJECT}/serviceAccounts/{BUILDER}",
        "sourceProvenance": {
            "resolvedConnectedRepository": {
                "revision": COMMIT,
            },
        },
        "results": {
            "images": [{
                "name": f"asia-southeast1-docker.pkg.dev/{PROJECT}/lab014-apps/shipping-quote-api:tag",
                "digest": DIGEST,
            }],
        },
    }
    value.update(changes)
    return value


class ReleasePipelineTests(unittest.TestCase):
    def test_accepts_exact_trigger_commit_builder_and_digest(self):
        result = module.verify_build_record(
            build_record(),
            project_id=PROJECT,
            trigger_id=TRIGGER,
            commit_sha=COMMIT,
            builder_email=BUILDER,
            region="asia-southeast1",
        )
        self.assertEqual(result["build_id"], "build-12345678")
        self.assertEqual(result["digest"], DIGEST)
        self.assertEqual(
            result["image_uri"],
            f"asia-southeast1-docker.pkg.dev/{PROJECT}/lab014-apps/shipping-quote-api@{DIGEST}",
        )

    def test_rejects_wrong_commit_trigger_builder_status_and_digest(self):
        cases = [
            ({"sourceProvenance": {"resolvedConnectedRepository": {"revision": "c" * 40}}}, "source revision"),
            ({"buildTriggerId": "other-trigger"}, "unexpected trigger"),
            ({"serviceAccount": "projects/other/serviceAccounts/" + BUILDER}, "builder identity"),
            ({"status": "FAILURE"}, "ended with status"),
            ({"results": {"images": []}}, "exactly one"),
            ({"results": {"images": [{"name": "wrong/image:tag", "digest": DIGEST}]}}, "exactly one"),
            ({"results": {"images": [{
                "name": f"asia-southeast1-docker.pkg.dev/{PROJECT}/lab014-apps/shipping-quote-api:tag",
                "digest": "sha256:bad",
            }]}}, "invalid image digest"),
        ]
        for changes, expected in cases:
            with self.subTest(expected=expected), self.assertRaisesRegex(module.ReleaseError, expected):
                module.verify_build_record(
                    build_record(**changes),
                    project_id=PROJECT,
                    trigger_id=TRIGGER,
                    commit_sha=COMMIT,
                    builder_email=BUILDER,
                    region="asia-southeast1",
                )

    def test_waits_for_matching_commit_and_rejects_duplicate_builds(self):
        success = build_record()
        with patch.object(module, "_run_gcloud", side_effect=[[], [success]]) as lookup, patch.object(
            module.time, "sleep"
        ):
            result = module.wait_for_verified_build(
                project_id=PROJECT,
                region="asia-southeast1",
                trigger_id=TRIGGER,
                commit_sha=COMMIT,
                builder_email=BUILDER,
                max_wait_seconds=30,
                poll_seconds=1,
            )
        self.assertEqual(result["build_id"], success["id"])
        self.assertEqual(lookup.call_count, 2)

        with patch.object(module, "_run_gcloud", return_value=[success, success]):
            with self.assertRaisesRegex(module.ReleaseError, "more than one build"):
                module.wait_for_verified_build(
                    project_id=PROJECT,
                    region="asia-southeast1",
                    trigger_id=TRIGGER,
                    commit_sha=COMMIT,
                    builder_email=BUILDER,
                    max_wait_seconds=30,
                    poll_seconds=1,
                )

    def test_cli_emits_only_validated_release_outputs(self):
        with patch.object(module, "wait_for_verified_build", return_value={
            "build_id": "build-12345678",
            "commit_sha": COMMIT,
            "digest": DIGEST,
            "image_uri": "asia-southeast1-docker.pkg.dev/lab-project-123/lab014-apps/shipping-quote-api@" + DIGEST,
        }) as verify, patch("builtins.print") as output:
            self.assertEqual(module.main([
                "--project-id", PROJECT,
                "--region", "asia-southeast1",
                "--trigger-id", TRIGGER,
                "--commit-sha", COMMIT,
                "--builder-email", BUILDER,
            ]), 0)
        verify.assert_called_once()
        self.assertIn('"result": "verified"', output.call_args.args[0])


class ReleaseWorkflowTests(unittest.TestCase):
    def test_release_workflow_is_main_only_and_uses_environments_for_wif(self):
        import yaml

        workflow = yaml.load((ROOT.parents[1] / ".github/workflows/release.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.assertEqual(workflow["on"]["push"]["branches"], ["main"])
        self.assertEqual(workflow["jobs"]["attest"]["environment"], "gcp-attest")
        self.assertEqual(workflow["jobs"]["release"]["environment"], "gcp-release")
        for name in ("attest", "release"):
            job = workflow["jobs"][name]
            self.assertEqual(job["permissions"]["id-token"], "write")
            self.assertTrue(any("google-github-actions/auth@" in step.get("uses", "") for step in job["steps"]))
            self.assertTrue(any("@3d3c42e5aac5ba805825da76410c181273ba90b1" in step.get("uses", "") for step in job["steps"]))
        self.assertIn("needs.attest.result == 'success'", workflow["jobs"]["release"]["if"])
        self.assertTrue(any("sign-and-create" in step.get("name", "") for step in workflow["jobs"]["attest"]["steps"]))
        self.assertTrue(any("shipping-quote-api=$IMAGE_URI" in step.get("run", "") for step in workflow["jobs"]["release"]["steps"]))


if __name__ == "__main__":
    unittest.main()
