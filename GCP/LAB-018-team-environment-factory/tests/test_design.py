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


class Lab018DesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svg = SVG.read_text(encoding="utf-8")
        cls.html = HTML.read_text(encoding="utf-8")
        cls.provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))

    def test_accessibility_and_embedded_preview_are_present(self):
        for value in ('role="img"', 'aria-labelledby="lab18-title lab18-desc"',
                      '<title id="lab18-title">', '<desc id="lab18-desc">'):
            self.assertIn(value, self.svg)
        self.assertIn(self.svg, self.html)
        self.assertNotRegex(self.svg, r'href="https?://')
        self.assertEqual(self.provenance["cloud_verification"], "not-run")

    def test_real_resource_hierarchy_and_separate_environments(self):
        for scope in ('id="org-scope"', 'id="folder-scope"', 'id="project-foundation"',
                      'id="project-dev"', 'id="project-staging"'):
            self.assertIn(scope, self.svg)
        self.assertLess(self.svg.index('id="project-dev"'), self.svg.index('id="project-staging"'))
        self.assertIn("asia-southeast1", self.svg)
        self.assertIn("Org policies ไม่เปลี่ยน", self.svg)

    def test_zip_personal_custom_style_and_icon_provenance_are_pinned(self):
        self.assertEqual(
            self.provenance["style"],
            "Diagram Design — Personal Custom from the user's diagram-design.zip",
        )
        self.assertEqual(
            self.provenance["source_commit"],
            "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192",
        )
        self.assertIn("#F7FAFF", self.svg)
        self.assertIn("#2563EB", self.svg)
        for name, data in self.provenance["icons"].items():
            self.assertEqual((ASSETS / data["path"].removeprefix("assets/")).exists(), True)
            content = (ASSETS / data["path"].removeprefix("assets/")).read_text(encoding="utf-8")
            git_blob_sha = hashlib.sha1(b"blob " + str(len(content.encode("utf-8"))).encode() + b"\0" + content.encode("utf-8")).hexdigest()
            self.assertEqual(git_blob_sha, data["git_blob_sha"])
            self.assertTrue(data["source_url"].endswith("/" + data["source_path"]))
            self.assertTrue(content.startswith("<svg"))

    def test_expected_routes_and_reviewed_layout_notes(self):
        self.assertIn("state read / write", self.svg)
        self.assertIn("Project log sink", self.svg)
        self.assertIn("lab18-arrow-blue", self.svg)
        self.assertIn("lab18-arrow-teal", self.svg)
        self.assertIn("junction", " ".join(self.provenance["layout_decisions"]))
        embedded = re.findall(r'href="data:image/svg\+xml;base64,', self.svg)
        self.assertGreaterEqual(len(embedded), 8)


if __name__ == "__main__":
    unittest.main()
