"""Validate Lab 09 accessible diagrams and pinned Google Cloud icon provenance."""
import base64
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
PROVENANCE = json.loads((ASSETS / "diagram-provenance.json").read_text(encoding="utf-8"))
SVG_NS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"
EXPECTED_SERVICES = {
    "Cloud Run", "Cloud Tasks", "Cloud Scheduler",
    "Firestore", "Secret Manager", "Cloud Storage",
}


class DiagramTests(unittest.TestCase):
    def test_diagrams_are_accessible_svg_with_nonempty_description(self):
        for name in ("solution", "delivery-flow"):
            root = ET.parse(ASSETS / f"{name}.svg").getroot()
            self.assertEqual(root.attrib.get("role"), "img")
            self.assertTrue(root.find(SVG_NS + "title").text)
            self.assertTrue(root.find(SVG_NS + "desc").text)

    def test_embedded_icons_match_pinned_provenance(self):
        self.assertEqual({entry["service"] for entry in PROVENANCE["icons"]}, EXPECTED_SERVICES)
        expected = {entry["sha256"] for entry in PROVENANCE["icons"]}
        root = ET.parse(ASSETS / "solution.svg").getroot()
        actual = set()
        for image in root.findall(".//" + SVG_NS + "image"):
            href = image.attrib.get(XLINK, "")
            self.assertTrue(href.startswith("data:image/svg+xml;base64,"))
            raw = base64.b64decode(href.split(",", 1)[1], validate=True)
            actual.add(hashlib.sha256(raw).hexdigest())
        self.assertEqual(actual, expected)
        self.assertEqual(PROVENANCE["pinned_icon_mirror"]["commit"],
                         "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")

    def test_diagrams_express_solution_and_recovery_contracts(self):
        topology = ET.parse(ASSETS / "solution.svg").getroot()
        flow = ET.parse(ASSETS / "delivery-flow.svg").getroot()
        topology_text = " ".join(item.text or "" for item in topology.findall(".//" + SVG_NS + "text"))
        flow_text = " ".join(item.text or "" for item in flow.findall(".//" + SVG_NS + "text"))
        for phrase in ("Event API", "Partner queue", "Delivery Worker",
                       "Partner Simulator A", "Firestore ledger", "Partner A key"):
            self.assertIn(phrase, topology_text)
        for phrase in ("enqueue_pending", "delivered", "permanent_failed",
                       "retry_ended_unknown", "generation + 1", "accept-then-503"):
            self.assertIn(phrase, flow_text)
        self.assertIn("cathrynlavery/diagram-design",
                      PROVENANCE["style_attribution"]["upstream"])


if __name__ == "__main__":
    unittest.main()
