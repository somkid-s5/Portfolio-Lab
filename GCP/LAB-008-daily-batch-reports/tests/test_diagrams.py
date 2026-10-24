"""Validate Lab 08 SVG accessibility and embedded official Google Cloud icons."""
import base64
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
PROVENANCE = json.loads((ASSETS / "diagram-provenance.json").read_text(encoding="utf-8"))
EXPECTED = {item["sha256"] for item in PROVENANCE["icons"]}
SVG_NS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"


class DiagramTests(unittest.TestCase):
    def test_solution_svg_embeds_all_verified_icons(self):
        root = ET.parse(ASSETS / "solution.svg").getroot()
        self.assertEqual(root.attrib.get("role"), "img")
        self.assertTrue(root.find(SVG_NS + "title").text)
        self.assertTrue(root.find(SVG_NS + "desc").text)
        hashes = set()
        for image in root.findall(".//" + SVG_NS + "image"):
            href = image.attrib.get(XLINK, "")
            if href.startswith("data:image/svg+xml;base64,"):
                icon = base64.b64decode(href.split(",", 1)[1], validate=True)
                hashes.add(hashlib.sha256(icon).hexdigest())
        self.assertEqual(hashes, EXPECTED)

    def test_flow_svg_is_accessible_and_provenance_is_complete(self):
        root = ET.parse(ASSETS / "run-flow.svg").getroot()
        self.assertEqual(root.attrib.get("role"), "img")
        self.assertTrue(root.find(SVG_NS + "title").text)
        self.assertTrue(root.find(SVG_NS + "desc").text)
        self.assertGreaterEqual(len(root.findall(".//" + SVG_NS + "rect")), 20)
        self.assertEqual(PROVENANCE["archive_sha256"], "a6d9d7921758042538b462f03cf64614c2cebd96743b3ed63580a769fc7de3e9")
        self.assertEqual({i["service"] for i in PROVENANCE["icons"]},
                         {"Cloud Run", "Cloud Scheduler", "Cloud Storage", "Firestore", "Pub/Sub"})
        self.assertEqual(PROVENANCE["style_attribution"]["license"], "MIT")
        self.assertIn("cathrynlavery/diagram-design", PROVENANCE["style_attribution"]["upstream"])


if __name__ == "__main__":
    unittest.main()
