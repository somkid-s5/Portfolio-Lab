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
SOLUTION = (ASSETS / "solution.svg").read_text(encoding="utf-8")
FLOW = (ASSETS / "recovery-flow.svg").read_text(encoding="utf-8")
PROVENANCE = json.loads((ASSETS / "diagram-provenance.json").read_text(encoding="utf-8"))
NS = {"svg": "http://www.w3.org/2000/svg"}


class Lab017DesignTests(unittest.TestCase):
    def test_diagrams_are_accessible_and_offline(self):
        for source in (SOLUTION, FLOW):
            root = ET.fromstring(source)
            self.assertEqual(root.attrib.get("role"), "img")
            self.assertTrue(root.find("svg:title", NS).text)
            self.assertTrue(root.find("svg:desc", NS).text)
            self.assertEqual(root.findall(".//svg:script", NS), [])
            for node in root.iter():
                for key, value in node.attrib.items():
                    if key.endswith("href"):
                        self.assertTrue(value.startswith("data:image/svg+xml;base64,"), value)

    def test_standalone_html_contains_committed_svg(self):
        for name, source in (("solution", SOLUTION), ("recovery-flow", FLOW)):
            html = (ASSETS / f"{name}.html").read_text(encoding="utf-8")
            start = html.index("<svg")
            end = html.index("</svg>", start) + len("</svg>")
            self.assertEqual(html[start:end], source)
            self.assertNotIn("<script src=", html)
            self.assertNotRegex(html, r'href=["\']https?://')

    def test_pinned_official_icons_are_embedded(self):
        self.assertEqual(PROVENANCE["official_icon_catalog"], "https://cloud.google.com/icons")
        self.assertEqual(PROVENANCE["source_commit"], "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
        self.assertEqual(PROVENANCE["cloud_verification"], "not-run")
        embedded = []
        for source in (SOLUTION, FLOW):
            embedded.extend(base64.b64decode(value) for value in re.findall(r'data:image/svg\+xml;base64,([^"]+)', source))
        for filename, item in PROVENANCE["icons"].items():
            icon = (ROOT / item["path"]).read_bytes()
            blob = b"blob " + str(len(icon)).encode("ascii") + b"\x00" + icon
            self.assertEqual(hashlib.sha1(blob).hexdigest(), item["git_blob_sha"], filename)
            self.assertIn(icon, embedded, filename)

    def test_personal_custom_scopes_palette_and_connections(self):
        root = ET.fromstring(SOLUTION)
        ids = {node.attrib.get("id") for node in root.iter()}
        for item in (
            "project-scope", "region-scope", "customer-vpc", "cloud-run-service",
            "run-egress-subnet", "sql-primary", "sql-recovery", "attachment-bucket",
            "soft-delete-policy", "active-to-primary", "recovery-to-clone",
            "pitr-to-clone", "run-to-bucket", "candidate-revision",
        ):
            self.assertIn(item, ids)
        for color in ("#F7FAFF", "#EFF6FF", "#F0FDFA", "#FFF7ED", "#F5F3FF", "#F1F5F9", "#F0FDF4"):
            self.assertIn(color, SOLUTION)
        for path_id in ("active-to-primary", "recovery-to-clone", "pitr-to-clone", "run-to-bucket"):
            node = next(n for n in root.iter() if n.attrib.get("id") == path_id)
            self.assertNotRegex(node.attrib.get("d", ""), r"[CQST]")

    def test_recovery_flow_keeps_parallel_paths_clear_and_requires_gate(self):
        root = ET.fromstring(FLOW)
        ids = {node.attrib.get("id") for node in root.iter()}
        for item in (
            "database-lane", "object-lane", "baseline-marker", "fault-injection",
            "pitr-recovery", "db-validation", "object-delete", "object-restore",
            "object-validation", "recovery-gate", "candidate-test",
            "traffic-promotion", "rpo-rto-record",
        ):
            self.assertIn(item, ids)
        self.assertIn("5-minute RPO and 30-minute RTO are exercise targets", FLOW)
        self.assertIn("new live copy; new generation", FLOW)


if __name__ == "__main__":
    unittest.main()
