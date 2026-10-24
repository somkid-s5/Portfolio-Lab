from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_skaffold_deploy_and_verifier_use_the_same_artifact(self):
        config = yaml.safe_load((ROOT / "skaffold.yaml").read_text(encoding="utf-8"))
        image = config["build"]["artifacts"][0]["image"]
        self.assertEqual(image, "shipping-quote-api")
        self.assertEqual(config["verify"][0]["container"]["image"], image)
        self.assertEqual(config["manifests"]["rawYaml"], ["deploy/service-staging.yaml"])
        self.assertEqual(config["profiles"][0]["manifests"]["rawYaml"], ["deploy/service-production.yaml"])
        self.assertIn("/srv/quote-api/tools/verify_quote.py", config["verify"][0]["container"]["command"])

    def test_cloud_deploy_requires_staging_verify_and_approved_canary(self):
        pipeline, staging, production = yaml.safe_load_all(
            (ROOT / "infra/clouddeploy.yaml").read_text(encoding="utf-8")
        )
        stages = pipeline["serialPipeline"]["stages"]
        self.assertEqual([stage["targetId"] for stage in stages], ["staging", "production"])
        self.assertIs(stages[0]["strategy"]["standard"]["verify"], True)
        canary = stages[1]["strategy"]["canary"]
        self.assertIs(canary["runtimeConfig"]["cloudRun"]["automaticTrafficControl"], True)
        self.assertEqual(canary["canaryDeployment"]["percentages"], [10, 50])
        self.assertIs(canary["canaryDeployment"]["verify"], True)
        cloud_run = canary["runtimeConfig"]["cloudRun"]
        self.assertEqual(cloud_run["canaryRevisionTags"], ["lab014-candidate"])
        self.assertEqual(cloud_run["stableRevisionTags"], ["lab014-stable"])
        self.assertIs(staging["requireApproval"], False)
        self.assertIs(production["requireApproval"], True)
        for target in (staging, production):
            self.assertEqual([item["usages"][0] for item in target["executionConfigs"]], ["RENDER", "DEPLOY", "VERIFY"])

    def test_both_services_are_bounded_and_use_same_runtime_identity(self):
        staging = yaml.safe_load((ROOT / "deploy/service-staging.yaml").read_text(encoding="utf-8"))
        production = yaml.safe_load((ROOT / "deploy/service-production.yaml").read_text(encoding="utf-8"))
        self.assertEqual(staging["metadata"]["name"], "quote-api-staging")
        self.assertEqual(production["metadata"]["name"], "quote-api-production")
        for service in (staging, production):
            spec = service["spec"]["template"]["spec"]
            self.assertEqual(spec["serviceAccountName"], "lab014-runtime@$PROJECT_ID.iam.gserviceaccount.com")
            container = spec["containers"][0]
            self.assertEqual(container["image"], "shipping-quote-api")
            self.assertEqual(container["resources"]["limits"], {"cpu": "1", "memory": "512Mi"})
            self.assertEqual(
                service["spec"]["template"]["metadata"]["annotations"]["autoscaling.knative.dev/maxScale"],
                "2",
            )
            self.assertEqual(container["env"][0]["value"], "1.00")

    def test_cloud_build_is_pinned_to_custom_builder_identity(self):
        config = yaml.safe_load((ROOT / "cloudbuild.yaml").read_text(encoding="utf-8"))
        self.assertEqual(
            config["serviceAccount"],
            "projects/$PROJECT_ID/serviceAccounts/lab014-builder@$PROJECT_ID.iam.gserviceaccount.com",
        )
        self.assertEqual(config["options"]["logging"], "CLOUD_LOGGING_ONLY")
        self.assertEqual(len(config["images"]), 1)


if __name__ == "__main__":
    unittest.main()
