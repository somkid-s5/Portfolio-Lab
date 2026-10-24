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
        self.assertIn("guide_status: design", README)
        self.assertIn("cloud_verification: not-run", README)
        self.assertIn("ยังไม่มีคู่มือ Task", README)
        self.assertNotRegex(README, r"(?m)^### Task [0-9]+")
        self.assertIn("Cloud verification: **Not run**", README)

    def test_requirements_cover_build_run_fail_recover_change_and_cleanup(self):
        for requirement in range(1, 11):
            self.assertIn("| R" + str(requirement) + " |", README)
        for phrase in ("Failure, Recovery", "Change Request", "หลักฐานที่จะบันทึก", "cleanup"):
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
        self.assertIn("Architecture design checkpoint", HTML)

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
