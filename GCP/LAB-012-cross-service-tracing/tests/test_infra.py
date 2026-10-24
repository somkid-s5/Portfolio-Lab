"""Offline checks for Terraform intent, generated Kubernetes resources and boundaries."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
MANIFEST = ROOT / "manifests" / "platform.yaml"
TERRAFORM = (ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
CLOUDBUILD = yaml.safe_load((ROOT / "cloudbuild.yaml").read_text(encoding="utf-8"))
RENDERER = ROOT / "scripts" / "render_manifests.py"


class Lab12InfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = list(yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")))
        cls.by_name = {doc["metadata"]["name"]: doc for doc in cls.docs if doc and "metadata" in doc}

    def test_terraform_declares_private_regional_autopilot_and_required_apis(self):
        for api in (
            "container.googleapis.com",
            "compute.googleapis.com",
            "artifactregistry.googleapis.com",
            "cloudbuild.googleapis.com",
            "telemetry.googleapis.com",
            "iamcredentials.googleapis.com",
        ):
            self.assertIn(api, TERRAFORM)
        self.assertIn('enable_autopilot    = true', TERRAFORM)
        self.assertIn('enable_private_nodes    = true', TERRAFORM)
        self.assertIn('ip_endpoints_config', TERRAFORM)
        self.assertIn('purpose       = "REGIONAL_MANAGED_PROXY"', TERRAFORM)
        self.assertIn('roles/telemetry.tracesWriter', TERRAFORM)
        self.assertIn('roles/serviceusage.serviceUsageConsumer', TERRAFORM)
        self.assertNotIn('google_service_account_key', TERRAFORM)
        self.assertNotIn('roles/owner', TERRAFORM)

    def test_cloud_build_uses_a_digest_ready_repository_and_cloud_logging(self):
        self.assertEqual(CLOUDBUILD["options"]["logging"], "CLOUD_LOGGING_ONLY")
        ids = [step["id"] for step in CLOUDBUILD["steps"]]
        self.assertEqual(ids, ["build-checkout-image", "push-checkout-image"])
        self.assertIn("checkout:", str(CLOUDBUILD["images"][0]))
        self.assertEqual(CLOUDBUILD["timeout"], "1200s")

    def test_services_are_internal_and_public_route_targets_storefront_only(self):
        services = [doc for doc in self.docs if doc and doc.get("kind") == "Service"]
        self.assertEqual({doc["metadata"]["name"] for doc in services}, {
            "otel-collector", "storefront", "order", "catalog", "payment"
        })
        self.assertTrue(all(doc.get("spec", {}).get("type", "ClusterIP") == "ClusterIP" for doc in services))
        gateway = self.by_name["checkout-gateway"]
        self.assertEqual(gateway["spec"]["gatewayClassName"], "gke-l7-regional-external-managed")
        self.assertEqual(gateway["spec"]["listeners"][0]["protocol"], "HTTPS")
        route = self.by_name["checkout-route"]
        self.assertEqual(route["spec"]["rules"][0]["backendRefs"][0]["name"], "storefront")
        self.assertNotIn("kind: Secret", MANIFEST.read_text(encoding="utf-8"))

    def test_ingress_network_policies_follow_the_service_graph(self):
        policies = {
            doc["metadata"]["name"]: doc
            for doc in self.docs
            if doc and doc.get("kind") == "NetworkPolicy"
        }
        self.assertEqual(set(policies), {
            "storefront-ingress", "order-ingress", "catalog-ingress",
            "payment-ingress", "collector-ingress"
        })
        by_name = {name: policies[name]["spec"] for name in policies}
        self.assertEqual(
            by_name["order-ingress"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"],
            "storefront",
        )
        self.assertEqual(
            by_name["catalog-ingress"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"],
            "order",
        )
        self.assertEqual(
            by_name["payment-ingress"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"],
            "order",
        )
        self.assertEqual(
            by_name["collector-ingress"]["ingress"][0]["ports"][0]["port"],
            4317,
        )
        self.assertEqual(len(by_name["order-ingress"]["ingress"]), 1)
        self.assertEqual(len(by_name["catalog-ingress"]["ingress"]), 1)
        self.assertEqual(len(by_name["payment-ingress"]["ingress"]), 1)

    def test_collector_is_trace_only_and_apps_do_not_receive_gcp_permissions(self):
        config = yaml.safe_load(self.by_name["otel-collector-config"]["data"]["config.yaml"])
        self.assertEqual(set(config["service"]["pipelines"]), {"traces"})
        self.assertEqual(
            config["service"]["pipelines"]["traces"]["exporters"],
            ["otlphttp/google"],
        )
        self.assertEqual(config["processors"]["resource/gcp_project_id"]["attributes"][0]["key"], "gcp.project_id")
        ksa = {
            doc["metadata"]["name"]: doc
            for doc in self.docs
            if doc and doc.get("kind") == "ServiceAccount"
        }
        for name in ("storefront", "order", "catalog", "payment"):
            self.assertFalse(ksa[name]["automountServiceAccountToken"])
        self.assertTrue(ksa["otel-collector"]["automountServiceAccountToken"])

    def test_renderer_requires_a_real_digest_and_removes_all_template_tokens(self):
        digest = "sha256:" + "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "platform.yaml"
            result = subprocess.run(
                [
                    sys.executable, str(RENDERER),
                    "--project", "demo-lab012",
                    "--image-uri", f"asia-southeast1-docker.pkg.dev/demo-lab012/lab012-images/checkout@{digest}",
                    "--gateway-ip-name", "lab012-gateway-ip",
                    "--output", str(output),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = output.read_text(encoding="utf-8")
            self.assertNotRegex(rendered, r"__[A-Z0-9_]+__")
            self.assertIn(f"checkout@{digest}", rendered)
            self.assertIn('project: "demo-lab012"', rendered)

    def test_renderer_rejects_tag_only_images(self):
        result = subprocess.run(
            [
                sys.executable, str(RENDERER),
                "--project", "demo-lab012",
                "--image-uri", "asia-southeast1-docker.pkg.dev/demo-lab012/lab012-images/checkout:latest",
                "--gateway-ip-name", "lab012-gateway-ip",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("@sha256", result.stderr)


if __name__ == "__main__":
    unittest.main()
