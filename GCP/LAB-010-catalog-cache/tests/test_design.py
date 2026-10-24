"""Validate Lab 10 design contracts, accessible diagrams and icon provenance."""
import base64
import hashlib
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
README = (ROOT / "README.md").read_text(encoding="utf-8")
PROVENANCE = json.loads((ASSETS / "diagram-provenance.json").read_text(encoding="utf-8"))
SVG_NS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"
EXPECTED_SERVICES = {
    "Cloud Run", "Cloud SQL", "Memorystore", "Cloud Logging",
    "Cloud Monitoring", "Secret Manager",
}


class DesignTests(unittest.TestCase):
    def test_readme_is_design_not_a_claim_of_cloud_execution(self):
        self.assertIn("phase: design", README)
        self.assertIn("guide_status: design", README)
        self.assertIn("cloud_verification: not-run", README)
        self.assertIn("last_verified: null", README)
        self.assertEqual(PROVENANCE["verification"]["cloud_deployment"], "not-run")
        self.assertIn("960px", PROVENANCE["verification"]["diagram_render"])
        self.assertIn("รวมไม่เกิน 2,500 requests", README)
        self.assertRegex(README, r"(?m)^## Design")
        self.assertNotRegex(README, r"(?m)^#{2,4}\s+Task\s+\d+")
        for requirement in range(1, 11):
            self.assertIn(f"R{requirement}", README)

    def test_auth_secret_handoff_does_not_claim_state_is_secret_free(self):
        self.assertIn("Terraform state ยังมี AUTH string", README)
        self.assertIn("sensitive แต่ Terraform ยังบันทึก", README)
        self.assertIn("pipe ผล", README)
        self.assertIn("gcloud secrets versions add --data-file=-", README)
        self.assertIn("ห้าม commit/อัปโหลด/แสดง state", README)
        self.assertNotIn("แยกจาก Terraform state", README)
        self.assertIn(
            "https://developer.hashicorp.com/terraform/language/manage-sensitive-data",
            README,
        )
        self.assertIn(
            "https://docs.cloud.google.com/sdk/gcloud/reference/secrets/versions/add",
            README,
        )

    def test_readme_local_links_resolve(self):
        pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
        for target in pattern.findall(README):
            target = target.split("#", 1)[0].strip()
            if not target or target.startswith(("https://", "http://", "mailto:")):
                continue
            self.assertTrue((ROOT / target).resolve().is_file(), target)

    def test_diagrams_are_accessible_svg_with_embedded_assets(self):
        for name in ("solution", "cache-flow"):
            root = ET.parse(ASSETS / f"{name}.svg").getroot()
            self.assertEqual(root.attrib.get("role"), "img")
            self.assertTrue(root.find(SVG_NS + "title").text)
            self.assertTrue(root.find(SVG_NS + "desc").text)
            self.assertFalse(any("http://" in (node.attrib.get(XLINK, "")) or
                                 "https://" in (node.attrib.get(XLINK, ""))
                                 for node in root.findall(".//" + SVG_NS + "image")))

    def test_embedded_service_icons_match_pinned_provenance(self):
        self.assertEqual({entry["service"] for entry in PROVENANCE["icon_source"]["files"]},
                         EXPECTED_SERVICES)
        self.assertEqual(PROVENANCE["icon_source"]["pinned_commit"],
                         "9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
        self.assertEqual(PROVENANCE["icon_source"]["official_entry_point"],
                         "https://cloud.google.com/icons")
        self.assertEqual(PROVENANCE["style_attribution"]["license"], "MIT")
        self.assertIn("cathrynlavery/diagram-design",
                      PROVENANCE["style_attribution"]["upstream"])
        expected = {entry["sha256"] for entry in PROVENANCE["icon_source"]["files"]}
        root = ET.parse(ASSETS / "solution.svg").getroot()
        actual = set()
        for image in root.findall(".//" + SVG_NS + "image"):
            href = image.attrib.get(XLINK, "")
            self.assertTrue(href.startswith("data:image/svg+xml;base64,"))
            raw = base64.b64decode(href.split(",", 1)[1], validate=True)
            actual.add(hashlib.sha256(raw).hexdigest())
        self.assertEqual(actual, expected)

    def test_topology_contains_solution_boundaries_and_roles(self):
        root = ET.parse(ASSETS / "solution.svg").getroot()
        content = " ".join(node.text or "" for node in root.findall(".//" + SVG_NS + "text"))
        for phrase in ("asia-southeast1", "catalog-public", "catalog-admin",
                       "Direct VPC egress", "Private Services Access",
                       "Cloud SQL", "Memorystore", "Secret Manager",
                       "Cloud Logging", "Cloud Monitoring", "Source of truth",
                       "AUTH + TLS", "IAM DB auth", "TCP 3307"):
            self.assertIn(phrase, content)
        self.assertIn("asia-southeast1", root.find(SVG_NS + "desc").text)

    def test_read_and_write_flow_documents_cache_failure_bounds(self):
        root = ET.parse(ASSETS / "cache-flow.svg").getroot()
        content = " ".join(node.text or "" for node in root.findall(".//" + SVG_NS + "text"))
        for phrase in ("GET catalog", "Redis GET", "Cache HIT", "MISS",
                       "SETEX 60s", "BYPASS", "250 ms", "If-Match",
                       "Commit to PostgreSQL", "Invalidate Redis keys",
                       "no FLUSHDB", "remaining 60s TTL", "sanitized 503"):
            self.assertIn(phrase, content)
        self.assertIn("no stale value is claimed current", root.find(SVG_NS + "desc").text.lower())


if __name__ == "__main__":
    unittest.main()
