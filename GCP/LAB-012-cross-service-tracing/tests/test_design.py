"""Lab 12 brief, diagram geometry, and official icon provenance checks."""
import base64
import hashlib
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
SVG = (ROOT / "assets" / "solution.svg").read_text(encoding="utf-8")
HTML = (ROOT / "assets" / "solution.html").read_text(encoding="utf-8")
PROVENANCE = json.loads((ROOT / "assets" / "diagram-provenance.json").read_text(encoding="utf-8"))
XLINK = "{http://www.w3.org/1999/xlink}href"
SVG_NS = "{http://www.w3.org/2000/svg}"


class Lab12DesignTests(unittest.TestCase):
    def test_brief_is_design_checkpoint_not_cloud_evidence(self):
        self.assertIn("phase: design", README)
        self.assertIn("guide_status: design", README)
        self.assertIn("cloud_verification: not-run", README)
        self.assertIn("## ผู้ใช้และผลลัพธ์ที่ต้องพิสูจน์", README)
        self.assertIn("## Solution design", README)
        self.assertIn("Expected เป็นเกณฑ์ตรวจ ไม่ใช่ผลจริง", README)
        for requirement in range(1, 10):
            self.assertIn(f"R{requirement}", README)
        self.assertNotRegex(README, r"(?m)^### Task \d{2} —")

    def test_svg_is_accessible_and_has_official_self_contained_icons(self):
        root = ET.fromstring(SVG)
        self.assertEqual(root.attrib.get("role"), "img")
        self.assertEqual(root.attrib.get("aria-labelledby"), "diagram-title diagram-desc")
        self.assertTrue(root.find(SVG_NS + "title").text)
        self.assertTrue(root.find(SVG_NS + "desc").text)
        descriptors = {item["svg_id"]: item for item in PROVENANCE["icon_source"]["files"]}
        embedded = root.findall(".//" + SVG_NS + "image")
        self.assertEqual(len(embedded), len(descriptors))
        for image in embedded:
            descriptor = descriptors[image.attrib["id"]]
            data_url = image.attrib[XLINK]
            self.assertTrue(data_url.startswith("data:image/svg+xml;base64,"))
            raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
            icon_path = ROOT / descriptor["local_path"]
            source = icon_path.read_bytes()
            git_blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
            self.assertEqual(raw, source)
            self.assertEqual(git_blob, descriptor["git_blob_sha"])
            self.assertIn("9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192", descriptor["source_url"])
        self.assertEqual(PROVENANCE["icon_source"]["official_entry_point"], "https://cloud.google.com/icons")
        self.assertEqual(PROVENANCE["icon_source"]["pinned_commit"], "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")

    def test_primary_paths_are_orthogonal_and_layout_is_short(self):
        root = ET.fromstring(SVG)
        paths = {item.attrib.get("id"): item.attrib.get("d", "") for item in root.findall(".//" + SVG_NS + "path") if item.attrib.get("id", "").startswith("flow-")}
        expected = {
            "flow-client-gateway", "flow-gateway-proxy", "flow-proxy-storefront",
            "flow-storefront-order", "flow-order-catalog", "flow-order-payment",
            "flow-services-collector", "flow-collector-trace", "flow-services-logging",
            "flow-build-artifacts", "flow-artifacts-gke",
        }
        self.assertEqual(set(paths), expected)
        for path in paths.values():
            self.assertTrue(set(re.findall(r"[A-Za-z]", path)) <= {"M", "H", "V"}, path)
        self.assertIn("M732 377H744V355H760", paths["flow-order-catalog"])
        self.assertIn("M732 407H744V443H760", paths["flow-order-payment"])\n        self.assertEqual(paths["flow-collector-trace"], "M822 540H900V320H1004")\n        self.assertEqual(paths["flow-services-logging"], "M845 488V580H945V520H1004")\n        self.assertNotIn("JSON stdout → GKE logs", SVG)
        self.assertIn("Catalog", SVG)
        self.assertIn("Payment mock", SVG)

    def test_standalone_html_contains_the_exact_inline_svg(self):
        match = re.search(r"(<svg\b.*?</svg>)", HTML, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), SVG.strip())

    def test_relative_document_links_resolve(self):
        for match in re.finditer(r"\]\(([^)]+)\)", README):
            target = match.group(1).strip()
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0].split(" ", 1)[0]
            if path:
                self.assertTrue((ROOT / path).resolve().is_file(), target)


if __name__ == "__main__":
    unittest.main()
