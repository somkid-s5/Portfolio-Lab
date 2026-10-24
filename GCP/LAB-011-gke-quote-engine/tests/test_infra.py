"""Offline validation of Lab 11 Terraform and Kubernetes manifests."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
MANIFEST_PATH = ROOT / "manifests" / "quote-platform.yaml"
MANIFESTS = list(yaml.safe_load_all(MANIFEST_PATH.read_text(encoding="utf-8")))
PROBE = yaml.safe_load((ROOT / "manifests" / "worker-boundary-probe.yaml").read_text(encoding="utf-8"))
BY_KIND_NAME = {(item["kind"], item["metadata"]["name"]): item for item in MANIFESTS}


class Lab11InfrastructureTests(unittest.TestCase):
    def test_terraform_is_a_private_regional_autopilot_foundation(self):
        self.assertIn('enable_autopilot    = true', MAIN)
        self.assertIn('networking_mode     = "VPC_NATIVE"', MAIN)
        self.assertIn('enable_private_nodes    = true', MAIN)
        self.assertIn('enable_private_endpoint = false', MAIN)
        self.assertIn('allow_external_traffic = true', MAIN)
        self.assertIn('enabled = false', MAIN)
        self.assertIn('workload_pool = "${var.project_id}.svc.id.goog"', MAIN)
        self.assertIn('private_ip_google_access = true', MAIN)
        self.assertIn('deletion_protection = !var.allow_destroy', MAIN)
        self.assertNotRegex(MAIN, r"(?m)^\s*secret_data\s*=")

    def test_secret_access_is_per_kubernetes_service_account(self):
        self.assertIn('subject/ns/quote-platform/sa/quote-api', MAIN)
        self.assertIn('subject/ns/quote-platform/sa/quote-worker', MAIN)
        self.assertIn('"roles/secretmanager.secretAccessor"', MAIN)
        self.assertIn('roles/iam.serviceAccountUser', MAIN)
        self.assertIn('roles/artifactregistry.reader', MAIN)
        self.assertIn('roles/artifactregistry.writer', MAIN)

    def test_kubernetes_services_do_not_publish_the_worker(self):
        self.assertEqual(len(MANIFESTS), 14)
        self.assertEqual(BY_KIND_NAME[("Service", "quote-api")]["spec"]["type"], "ClusterIP")
        self.assertEqual(BY_KIND_NAME[("Service", "quote-worker")]["spec"]["type"], "ClusterIP")
        route = BY_KIND_NAME[("HTTPRoute", "quote-route")]["spec"]
        backends = route["rules"][0]["backendRefs"]
        self.assertEqual(backends, [{"name": "quote-api", "port": 8080}])
        self.assertNotIn("quote-worker", str(route))

    def test_hpa_and_container_safety_contracts_are_present(self):
        hpa = BY_KIND_NAME[("HorizontalPodAutoscaler", "quote-worker")]["spec"]
        self.assertEqual((hpa["minReplicas"], hpa["maxReplicas"]), (1, 4))
        self.assertEqual(hpa["metrics"][0]["resource"]["target"]["averageUtilization"], 60)
        for name, deployment, container_name in (
            ("api", BY_KIND_NAME[("Deployment", "quote-api")], "api"),
            ("worker", BY_KIND_NAME[("Deployment", "quote-worker")], "worker"),
        ):
            pod_spec = deployment["spec"]["template"]["spec"]
            container = next(c for c in pod_spec["containers"] if c["name"] == container_name)
            self.assertEqual(pod_spec["serviceAccountName"], f"quote-{name}")
            self.assertIn("startupProbe", container)
            self.assertIn("readinessProbe", container)
            self.assertIn("livenessProbe", container)
            self.assertRegex(container["resources"]["requests"]["cpu"], r"^\d+m$")
            self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
            self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])

    def test_worker_network_policy_only_selects_api_pods(self):
        policy = BY_KIND_NAME[("NetworkPolicy", "quote-worker-ingress")]["spec"]
        self.assertEqual(policy["podSelector"]["matchLabels"], {"app": "quote-worker"})
        self.assertEqual(
            policy["ingress"][0]["from"][0]["podSelector"]["matchLabels"],
            {"app": "quote-api"},
        )
        self.assertEqual(policy["ingress"][0]["ports"][0]["port"], 8081)
        self.assertEqual(PROBE["metadata"]["labels"]["app"], "boundary-probe")
        self.assertNotEqual(PROBE["metadata"]["labels"]["app"], "quote-api")

    def test_regional_gateway_requires_named_address_https_and_test_hostname(self):
        gateway = BY_KIND_NAME[("Gateway", "quote-gateway")]["spec"]
        self.assertEqual(gateway["gatewayClassName"], "gke-l7-regional-external-managed")
        self.assertEqual(gateway["addresses"][0]["value"], "lab011-gateway-ip")
        self.assertEqual(gateway["listeners"][0]["protocol"], "HTTPS")
        route = BY_KIND_NAME[("HTTPRoute", "quote-route")]["spec"]
        self.assertEqual(route["hostnames"], ["quote.lab.test"])
        self.assertIn("REGIONAL_MANAGED_PROXY", MAIN)


if __name__ == "__main__":
    unittest.main()
