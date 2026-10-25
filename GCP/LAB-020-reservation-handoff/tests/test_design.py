from pathlib import Path
import base64
import hashlib
import json
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SVG_PATH = ASSETS / "solution.svg"
HTML_PATH = ASSETS / "solution.html"
PROVENANCE_PATH = ASSETS / "diagram-provenance.json"


class Lab020DesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svg = SVG_PATH.read_text(encoding="utf-8")
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        cls.provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))

    def test_accessible_embedded_svg_and_offline_preview(self):
        for value in ('role="img"', 'aria-labelledby="lab20-title lab20-desc"',
                      '<title id="lab20-title">', '<desc id="lab20-desc">'):
            self.assertIn(value, self.svg)
        self.assertIn(self.svg, self.html)
        self.assertNotRegex(self.svg, r'href="https?://')
        self.assertEqual(self.provenance["cloud_verification"], "not-run")
        ET.fromstring(self.svg)

    def test_provider_project_region_and_vpc_scopes_are_truthful(self):
        for item in ('id="project-scope"', 'id="region-scope"', 'id="vpc-scope"',
                     'id="api-service"', 'id="worker-service"', 'id="sql-resource"',
                     'id="pubsub-resource"', 'id="storage-resource"',
                     'id="logging-resource"', 'id="monitoring-resource"'):
            self.assertIn(item, self.svg)
        self.assertIn("asia-southeast1", self.svg)
        self.assertIn("single-zone", " ".join(self.provenance["layout_decisions"]))
        self.assertIn("Direct VPC egress", self.svg)
        self.assertIn("Private Services Access", self.svg)
        self.assertIn("IAP", self.svg)

    def test_flow_routes_use_zip_style_and_orthogonal_connectors(self):
        for route in ("route-staff-iap", "route-iap-api", "route-api-pubsub",
                      "route-pubsub-worker", "route-api-vpc", "route-worker-vpc",
                      "route-vpc-psa", "route-psa-sql", "route-worker-storage", "route-api-storage",
                      "route-api-logging", "route-worker-logging",
                      "route-logging-monitoring", "route-build-artifact",
                      "route-artifact-release"):
            self.assertIn(f'id="{route}"', self.svg)
        self.assertIn("#F7FAFF", self.svg)
        self.assertIn("#2563EB", self.svg)
        self.assertNotRegex(self.svg, r"filter:|linearGradient|feGaussianBlur")
        paths = re.findall(r'<path id="route-[^"]+"[^>]* d="([^"]+)"', self.svg)
        self.assertGreaterEqual(len(paths), 14)
        for path in paths:
            self.assertRegex(path, r"^[M0-9 .HV-]+$")
        self.assertIn("IAP is a labeled generic access gate", " ".join(self.provenance["generic_fallbacks"]))
        route_data = dict(re.findall(r'<path id="(route-[^"]+)"[^>]* d="([^"]+)"', self.svg))
        for route, path in route_data.items():
            current = [float(value) for value in re.match(r"M(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)", path).groups()]
            segments = []
            for axis, value in re.findall(r"([HV])(-?\d+(?:\.\d+)?)", path):
                target = float(value)
                index = 0 if axis == "H" else 1
                segments.append(abs(target - current[index]))
                current[index] = target
            if route == "route-api-logging":
                self.assertLessEqual(max(segments), 660, route)
            else:
                self.assertLessEqual(max(segments), 260, route)
        self.assertNotIn("H930V345H552", self.svg)
        self.assertIn("without perimeter loops", " ".join(self.provenance["layout_decisions"]))

    def test_zip_style_and_official_icon_bytes_are_pinned(self):
        self.assertEqual(
            self.provenance["style"],
            "Diagram Design — Personal Custom from the user's diagram-design.zip",
        )
        self.assertEqual(self.provenance["style_source_commit"], "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
        self.assertEqual(self.provenance["icon_source_commit"], "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
        self.assertEqual(self.provenance["render_target_width"], 1000)
        for name, data in self.provenance["icons"].items():
            path = ROOT / data["path"]
            content = path.read_text(encoding="utf-8")
            payload = content.encode("utf-8")
            digest = hashlib.sha1(
                b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
            ).hexdigest()
            self.assertEqual(digest, data["git_blob_sha"], name)
            self.assertTrue(content.startswith("<svg"), name)
            self.assertTrue(data["source_url"].endswith("/" + data["source_path"]), name)
            encoded = base64.b64encode(payload).decode("ascii")
            self.assertIn(encoded, self.svg, name)


if __name__ == "__main__":
    unittest.main()
