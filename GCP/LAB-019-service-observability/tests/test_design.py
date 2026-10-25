from pathlib import Path
import hashlib
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SVG = ASSETS / "solution.svg"
HTML = ASSETS / "solution.html"
PROVENANCE = ASSETS / "diagram-provenance.json"


class Lab019DesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svg = SVG.read_text(encoding="utf-8")
        cls.html = HTML.read_text(encoding="utf-8")
        cls.provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))

    def test_svg_accessibility_and_standalone_preview(self):
        for value in ('role="img"', 'aria-labelledby="lab19-title lab19-desc"',
                      '<title id="lab19-title">', '<desc id="lab19-desc">'):
            self.assertIn(value, self.svg)
        self.assertIn(self.svg, self.html)
        self.assertNotRegex(self.svg, r'href="https?://')
        self.assertEqual(self.provenance["cloud_verification"], "not-run")

    def test_scopes_match_the_gcp_resource_model(self):
        for scope in ('id="project-scope"', 'id="region-scope"', 'id="vpc-scope"',
                      'id="run-services"', 'id="pubsub-resource"', 'id="sql-resource"'):
            self.assertIn(scope, self.svg)
        self.assertIn("asia-southeast1", self.provenance["layout_decisions"][0] + self.svg)
        self.assertIn("Direct VPC egress", self.svg)
        self.assertIn("Private Services Access", self.svg)
        self.assertIn("Cloud SQL", self.svg)
        self.assertIn("Schema Migrator", self.svg)

    def test_request_routes_and_separate_auth_telemetry_paths_exist(self):
        for route in ("route-client-api", "route-api-pubsub", "route-pubsub-worker", "route-dlq-status", "route-migrator-vpc",
                      "route-api-vpc", "route-worker-vpc", "route-vpc-sql",
                      "route-monitoring-probe", "route-alert-oncall"):
            self.assertIn(f'id="{route}"', self.svg)
        self.assertIn("OIDC", self.svg)
        self.assertIn("DLQ status · OIDC", self.svg)
        self.assertIn("telemetry", self.svg)
        self.assertIn("not every request", self.svg)
        self.assertIn("junction", " ".join(self.provenance["layout_decisions"]).lower())

    def test_zip_style_and_pinned_official_icons_are_preserved(self):
        self.assertEqual(self.provenance["style"],
                         "Diagram Design — Personal Custom from the user's diagram-design.zip")
        self.assertEqual(self.provenance["style_source_commit"],
                         "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
        self.assertEqual(self.provenance["icon_source_commit"],
                         "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
        self.assertIn("#F7FAFF", self.svg)
        self.assertIn("#2563EB", self.svg)
        self.assertNotRegex(self.svg, r"filter:|linearGradient|feGaussianBlur")
        for name, data in self.provenance["icons"].items():
            path = ASSETS / data["path"].removeprefix("assets/")
            content = path.read_text(encoding="utf-8")
            encoded = content.encode("utf-8")
            digest = hashlib.sha1(b"blob " + str(len(encoded)).encode() + b"\0" + encoded).hexdigest()
            self.assertEqual(digest, data["git_blob_sha"], name)
            self.assertTrue(data["source_url"].endswith("/" + data["source_path"]))
            self.assertTrue(content.startswith("<svg"))
            self.assertIn("data:image/svg+xml;base64,", self.svg)


if __name__ == "__main__":
    unittest.main()
