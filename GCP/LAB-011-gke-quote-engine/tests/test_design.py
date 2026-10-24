"""Lab 11 design and diagram provenance checks (no GCP calls)."""
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


class Lab11DesignTests(unittest.TestCase):
    def test_authoring_checkpoint_and_cloud_status_are_honest(self):
        self.assertIn("phase: authoring", README)
        self.assertIn("guide_status: authoring", README)
        self.assertIn("cloud_verification: not-run", README)
        self.assertIn("Guide ยังเขียนไม่ครบทุก Task", README)
        for requirement in range(1, 11):
            self.assertIn(f"R{requirement}", README)
        self.assertNotRegex(README, r"(?m)^### Task \d{2}")
        self.assertIn("DNS-based control-plane endpoint", README)
        self.assertIn("0.0.0.0/0", README)

    def test_solution_diagram_is_accessible_and_offline(self):
        root = ET.fromstring(SVG)
        self.assertEqual(root.attrib.get("role"), "img")
        self.assertIn("title", root.attrib.get("aria-labelledby", ""))
        self.assertTrue(root.find(SVG_NS + "title").text)
        self.assertTrue(root.find(SVG_NS + "desc").text)
        images = root.findall(".//" + SVG_NS + "image")
        self.assertEqual(len(images), len(PROVENANCE["icon_source"]["files"]))
        for image in images:
            href = image.attrib.get(XLINK, "")
            self.assertTrue(href.startswith("data:image/svg+xml;base64,"))
            self.assertNotRegex(href, r"(?i)^https?://")

    def test_gateway_route_is_short_orthogonal_and_label_is_out_of_the_route(self):
        self.assertIn('d="M235 550H300V614H355"', SVG)
        self.assertIn('x="248" y="508">TLS → API :8080</text>', SVG)
        self.assertNotIn('x="248" y="575"', SVG)

    def test_official_icon_hashes_match_pinned_source(self):
        embedded = {}
        for image in ET.fromstring(SVG).findall(".//" + SVG_NS + "image"):
            href = image.attrib[XLINK]
            raw = base64.b64decode(href.split(",", 1)[1], validate=True)
            digest = hashlib.sha256(raw).hexdigest()
            embedded[digest] = raw
        expected = {item["sha256"] for item in PROVENANCE["icon_source"]["files"]}
        self.assertEqual(set(embedded), expected)
        self.assertEqual(PROVENANCE["icon_source"]["pinned_commit"], "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
        self.assertEqual(PROVENANCE["icon_source"]["official_entry_point"], "https://cloud.google.com/icons")
        self.assertIn("CI #312", PROVENANCE["verification"]["diagram_render"])

    def test_standalone_html_contains_exact_editable_svg(self):
        match = re.search(r"(<svg\b.*?</svg>)", HTML, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), SVG.strip())

    def test_relative_document_links_exist(self):
        for match in re.finditer(r"\]\(([^)]+)\)", README):
            target = match.group(1).strip()
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0].split(" ", 1)[0]
            if path:
                self.assertTrue((ROOT / path).resolve().is_file(), target)
        self.assertIn("assets/solution.svg", README)
        self.assertIn("assets/solution.html", README)


if __name__ == "__main__":
    unittest.main()
