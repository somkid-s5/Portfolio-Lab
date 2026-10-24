from __future__ import annotations

import base64
import hashlib
import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SVG = (ASSETS / "solution.svg").read_text(encoding="utf-8")
HTML = (ASSETS / "solution.html").read_text(encoding="utf-8")
PROVENANCE = json.loads((ASSETS / "diagram-provenance.json").read_text(encoding="utf-8"))
NS = {"svg": "http://www.w3.org/2000/svg"}


class DiagramTests(unittest.TestCase):
    def test_svg_is_accessible_offline_and_valid(self):
        root = ET.fromstring(SVG)
        self.assertEqual(root.attrib.get("role"), "img")
        self.assertIn("aria-labelledby", root.attrib)
        self.assertTrue(root.find("svg:title", NS).text)
        self.assertTrue(root.find("svg:desc", NS).text)
        self.assertEqual(root.findall(".//svg:script", NS), [])
        for node in root.iter():
            for name, value in node.attrib.items():
                if name.endswith("href"):
                    self.assertTrue(value.startswith("data:image/svg+xml;base64,"), value)

    def test_standalone_html_contains_exact_committed_svg(self):
        start = HTML.index("<svg")
        end = HTML.index("</svg>", start) + len("</svg>")
        self.assertEqual(HTML[start:end], SVG)
        self.assertNotIn("<script src=", HTML)
        self.assertNotIn("https://", HTML)

    def test_icons_are_pinned_and_embedded(self):
        self.assertEqual(PROVENANCE["official_icon_catalog"], "https://cloud.google.com/icons")
        self.assertEqual(PROVENANCE["cloud_verification"], "not-run")
        self.assertEqual(PROVENANCE["source_commit"], "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
        embedded = re.findall(r'data:image/svg\+xml;base64,([^"]+)', SVG)
        decoded = [base64.b64decode(value) for value in embedded]
        self.assertGreaterEqual(len(decoded), len(PROVENANCE["icons"]))
        for filename, source in PROVENANCE["icons"].items():
            icon = (ROOT / source["path"]).read_bytes()
            git_blob = b"blob " + str(len(icon)).encode("ascii") + b"\x00" + icon
            self.assertEqual(hashlib.sha1(git_blob).hexdigest(), source["git_blob_sha"], filename)
            self.assertIn(icon, decoded, filename)

    def test_scope_and_topology_labels_have_stable_ids(self):
        root = ET.fromstring(SVG)
        nodes = {item.attrib["id"]: item for item in root.iter() if "id" in item.attrib}
        for identifier in ("project-scope", "region-scope", "branch-vpc", "hub-vpc", "branch-probe",
                           "branch-vpn", "hub-vpn", "branch-router", "hub-router", "tunnel-a",
                           "tunnel-b", "internal-lb", "inventory-run", "private-dns"):
            self.assertIn(identifier, nodes)
        for identifier in ("tunnel-a", "tunnel-b"):
            path = nodes[identifier]
            self.assertIn("H", path.attrib["d"])
            self.assertNotIn("V", path.attrib["d"])
        self.assertEqual(nodes["vpn-to-service"].attrib["d"], "M1122 586H1195V690H1415")
        self.assertEqual(nodes["lb-to-run"].attrib["d"], "M1458 650V390")
        self.assertEqual(nodes["iap-to-branch-probe"].attrib["d"], "M90 702H245")
        iap = nodes["iap-admin"].find("svg:image", NS)
        branch = nodes["branch-vpc"]
        self.assertLessEqual(float(iap.attrib["x"]) + float(iap.attrib["width"]), float(branch.attrib["x"]))
        labels = " ".join(item.text or "" for item in root.iter() if item.tag.endswith("text"))
        for label in ("10.70.0.0/24", "10.60.0.0/24", "10.70.1.0/24", "inventory.lab.internal"):
            self.assertIn(label, labels)


if __name__ == "__main__":
    unittest.main()
