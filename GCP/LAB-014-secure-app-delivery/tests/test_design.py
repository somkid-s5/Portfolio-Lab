import base64
import hashlib
import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SVG_PATH = ASSETS / "solution.svg"
HTML_PATH = ASSETS / "solution.html"
PROVENANCE_PATH = ASSETS / "diagram-provenance.json"
README_PATH = ROOT / "README.md"
SVG = SVG_PATH.read_text(encoding="utf-8")
HTML = HTML_PATH.read_text(encoding="utf-8")
README = README_PATH.read_text(encoding="utf-8")
PROVENANCE = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
NS = {"svg": "http://www.w3.org/2000/svg"}


class Lab14DesignTests(unittest.TestCase):
    def test_svg_is_accessible_and_has_no_remote_dependencies(self):
        root = ET.fromstring(SVG)
        self.assertEqual(root.attrib.get("role"), "img")
        self.assertTrue(root.find("svg:title", NS).text)
        self.assertTrue(root.find("svg:desc", NS).text)
        self.assertEqual(root.findall(".//svg:script", NS), [])
        for element in root.iter():
            for name, value in element.attrib.items():
                if name.endswith("href"):
                    self.assertTrue(value.startswith("data:image/svg+xml;base64,"), value)

    def test_standalone_html_contains_the_exact_saved_svg(self):
        start = HTML.index("<svg")
        end = HTML.index("</svg>", start) + len("</svg>")
        self.assertEqual(HTML[start:end], SVG)
        self.assertNotIn("<script src=", HTML)
        self.assertNotIn("https://", HTML)

    def test_official_icons_are_local_embedded_and_pinned(self):
        self.assertEqual(PROVENANCE["official_icon_catalog"], "https://cloud.google.com/icons")
        self.assertEqual(PROVENANCE["cloud_verification"], "not-run")
        self.assertRegex(PROVENANCE["source_commit"], r"^[0-9a-f]{40}$")
        embedded = re.findall(r"data:image/svg\+xml;base64,([^\"]+)", SVG)
        decoded = [base64.b64decode(value) for value in embedded]
        for filename, source in PROVENANCE["icons"].items():
            icon = (ASSETS / source["path"].removeprefix("assets/")).read_bytes()
            self.assertIn(icon, decoded, filename)
            if "git_blob_sha" in source:
                self.assertRegex(source["git_blob_sha"], r"^[0-9a-f]{40}$")
                git_blob = b"blob " + str(len(icon)).encode("ascii") + b"\x00" + icon
                self.assertEqual(hashlib.sha1(git_blob).hexdigest(), source["git_blob_sha"], filename)
            else:
                self.assertRegex(source["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(hashlib.sha256(icon).hexdigest(), source["sha256"], filename)
        self.assertIn("generic symbols", PROVENANCE["attribution"])

    def test_scope_and_connectivity_choose_short_vertical_runtime_stack(self):
        root = ET.fromstring(SVG)
        by_id = {node.attrib["id"]: node for node in root.iter() if "id" in node.attrib}
        project = by_id["project-scope"].attrib
        region = by_id["region-scope"].attrib
        wif = by_id["wif-pool"].attrib
        self.assertLess(int(wif["x"]), int(region["x"]))
        self.assertGreater(int(region["x"]), int(project["x"]))
        for name in ("cloud-build", "artifact-registry", "cloud-deploy", "kms-signer",
                     "staging-target", "production-target"):
            box = by_id[name].attrib
            self.assertGreaterEqual(int(box["x"]), int(region["x"]), name)
            self.assertLessEqual(int(box["x"]) + int(box["width"]),
                                 int(region["x"]) + int(region["width"]), name)
        centers = []
        for name in ("cloud-deploy", "staging-target", "production-target"):
            box = by_id[name].attrib
            centers.append(int(box["x"]) + int(box["width"]) / 2)
        self.assertEqual(centers, [centers[0]] * len(centers))
        self.assertLess(int(by_id["staging-target"].attrib["y"]),
                        int(by_id["production-target"].attrib["y"]))
        for path_id in ("github-to-wif", "github-push-to-build", "kms-to-attestor", "build-to-registry",
                        "registry-to-deploy", "deploy-to-staging", "policy-to-runtime-gate"):
            self.assertIn(path_id, by_id)
        self.assertNotIn("wif-to-build", by_id)
        self.assertEqual(by_id["github-push-to-build"].attrib["d"], "M280 413H300V230H670V255")

    def test_readme_locks_the_github_build_and_wif_trust_boundary(self):
        for phrase in (
            "GitHub WIF ไม่มีสิทธิ์ `cloudbuild.builds.create`",
            "google.subject=assertion.sub",
            "attribute.repository_id=assertion.repository_id",
            "attribute.ref=assertion.ref",
            "attribute.workflow_ref=assertion.workflow_ref",
            "attribute.environment=assertion.environment",
            "`gcp-attest`",
            "`gcp-release`",
            "trigger ID, commit SHA, builder identity",
            "`lab014-renderer`",
            "`lab014-staging-deployer`",
            "`lab014-production-deployer`",
            "`roles/containeranalysis.notes.occurrences.viewer`",
        ):
            self.assertIn(phrase, README)
        self.assertIn("cloud_verification: not-run", README)
        self.assertIn("สถานะ Cloud:** Not run", README)

    def test_trust_and_delivery_labels_are_explicit(self):
        for phrase in (
            "main • release env only", "repo_id 1428247317", "CI only • no GCP token", "GitHub push trigger",
            "same AR digest", "Manual production approval", "10% → 50% → 100%",
            "project-level scope", "required signed attestation before revision admission",
            "Cloud Logging",
        ):
            self.assertIn(phrase, SVG)


if __name__ == "__main__":
    unittest.main()
