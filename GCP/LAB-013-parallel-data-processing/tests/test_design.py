import base64
import hashlib
import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
README = (LAB / "README.md").read_text(encoding="utf-8")
SVG = (LAB / "assets/solution.svg").read_text(encoding="utf-8")
HTML = (LAB / "assets/solution.html").read_text(encoding="utf-8")
PROVENANCE = json.loads((LAB / "assets/diagram-provenance.json").read_text(encoding="utf-8"))

class DesignCheckpointTests(unittest.TestCase):
    def test_checkpoint_is_design_only_and_not_cloud_verified(self):
        self.assertIn("guide_status: guide-ready", README)
        self.assertRegex(README, r"(?m)^cloud_verification: not-run$")
        self.assertIn("**Cloud verification:** Not run", README)
        self.assertRegex(README, r"(?m)^### Task 19 — Cleanup")
        self.assertIn("RETRY_TASK เฉพาะ exit code 75", README)
        self.assertIn("exit code 65 ที่ไม่อยู่ใน allowlist", README)
        self.assertIn("Artifact Registry Reader", README)
        self.assertIn("roles/artifactregistry.reader", README)
        self.assertIn("Operator", README)
        self.assertIn("Storage Object Viewer (roles/storage.objectViewer) เฉพาะ input, attempt-output และ published buckets", README)
        self.assertIn("roles/storage.objectCreator) เฉพาะ input (append source objects)", README)
        self.assertIn("published (publish manifest)", README)
        self.assertIn("roles/serviceusage.serviceUsageConsumer", README)
        self.assertIn("soft delete เป็น 0", README)
        self.assertIn("probe ที่ได้ 403 ทั้งสอง bucket", README)
        for role_id in (
            "roles/cloudbuild.builds.editor", "roles/batch.jobsEditor",
            "roles/compute.networkViewer", "roles/logging.viewer",
            "roles/iam.serviceAccountUser", "roles/serviceusage.serviceUsageConsumer", "roles/artifactregistry.writer",
            "roles/batch.agentReporter", "roles/logging.logWriter",
            "roles/storage.objectViewer", "roles/storage.objectCreator",
            "roles/batch.serviceAgent",
        ):
            self.assertIn(role_id, README)
        self.assertNotIn("FAIL_TASK", README)

    def test_requirements_cover_build_run_fail_recover_change_and_cleanup(self):
        for requirement in range(1, 11):
            self.assertIn("| R" + str(requirement) + " |", README)
        for phrase in ("malformed", "Recovery", "Change Request", "หลักฐานที่เก็บ", "cleanup"):
            self.assertIn(phrase.lower(), README.lower())

    def test_architecture_and_scope_are_present(self):
        for name in ("Cloud Build", "Artifact Registry", "Cloud Batch", "Cloud Storage",
                     "Compute Engine", "Cloud Logging", "asia-southeast1",
                     "Private Google Access", "at-least-once"):
            self.assertIn(name, README)
        root = ET.fromstring(SVG)
        ns = {"s": "http://www.w3.org/2000/svg"}
        self.assertEqual(root.attrib.get("viewBox"), "0 0 1500 940")
        project = root.find(".//s:rect[@class='boundary']", ns)
        operator = root.find(".//s:circle[@cx='790']", ns)
        self.assertIsNotNone(project)
        self.assertIsNotNone(operator)
        self.assertLess(float(operator.attrib["cy"]), float(project.attrib["y"]))
        self.assertTrue(root.findall(".//s:rect", ns))
        self.assertGreaterEqual(len(root.findall(".//s:path[@class='edge']", ns)), 4)
        self.assertGreaterEqual(len(root.findall(".//s:path[@class='data']", ns)), 2)
        self.assertGreaterEqual(len(root.findall(".//s:path[@class='control']", ns)), 1)

    def test_connections_are_orthogonal_and_avoid_curve_routes(self):
        root = ET.fromstring(SVG)
        ns = {"s": "http://www.w3.org/2000/svg"}
        routes = root.findall(".//s:path[@class='edge']", ns)
        routes += root.findall(".//s:path[@class='data']", ns)
        routes += root.findall(".//s:path[@class='control']", ns)
        self.assertGreaterEqual(len(routes), 8)
        for route in routes:
            data = route.attrib["d"]
            self.assertNotRegex(data, r"[CcQqSsTt]")
            self.assertRegex(data, r"^M[0-9 .-]+(?:[HV][0-9 .-]+)+$")

    def test_standalone_html_contains_exact_saved_svg(self):
        self.assertIn(SVG, HTML)
        self.assertIn('lang="th"', HTML)
        self.assertIn("Lab 13 solution diagram", HTML)

    def test_official_icon_payloads_match_pinned_git_blob_hashes(self):
        self.assertEqual(PROVENANCE["source_commit"], "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
        self.assertEqual(PROVENANCE["cloud_verification"], "not-run")
        self.assertEqual(set(PROVENANCE["icons"]), {
            "batch.svg", "cloud_storage.svg", "compute_engine.svg",
            "identity_and_access_management.svg", "cloud_build.svg",
            "artifact_registry.svg", "cloud_logging.svg"})
        for filename, item in PROVENANCE["icons"].items():
            raw = (LAB / item["path"]).read_bytes()
            blob = b"blob " + str(len(raw)).encode("ascii") + bytes([0]) + raw
            self.assertEqual(hashlib.sha1(blob).hexdigest(), item["git_blob_sha"], filename)
            self.assertIn(base64.b64encode(raw).decode("ascii"), SVG)
            self.assertIn("cloud.google.com/icons", PROVENANCE["official_icon_catalog"])
            self.assertIn("Google Cloud attribution", PROVENANCE["attribution"])
        self.assertIn("data:image/svg+xml;base64,", SVG)

if __name__ == "__main__":
    unittest.main()
