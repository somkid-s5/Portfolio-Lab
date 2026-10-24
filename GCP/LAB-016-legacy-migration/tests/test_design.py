from __future__ import annotations
import base64, hashlib, json, re, unittest
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/"assets"
NS={"svg":"http://www.w3.org/2000/svg"}
SOLUTION=(ASSETS/"solution.svg").read_text(encoding="utf-8")
FLOW=(ASSETS/"migration-flow.svg").read_text(encoding="utf-8")
PROVENANCE=json.loads((ASSETS/"diagram-provenance.json").read_text(encoding="utf-8"))
class Lab016DesignTests(unittest.TestCase):
 def test_diagrams_are_accessible_and_offline(self):
  for source in (SOLUTION,FLOW):
   root=ET.fromstring(source); self.assertEqual(root.attrib.get("role"),"img")
   self.assertTrue(root.find("svg:title",NS).text); self.assertTrue(root.find("svg:desc",NS).text)
   self.assertEqual(root.findall(".//svg:script",NS),[])
   for node in root.iter():
    for key,value in node.attrib.items():
     if key.endswith("href"): self.assertTrue(value.startswith("data:image/svg+xml;base64,"),value)
 def test_standalone_html_contains_committed_svg_exactly(self):
  for name,source in (("solution",SOLUTION),("migration-flow",FLOW)):
   html=(ASSETS/f"{name}.html").read_text(encoding="utf-8"); start=html.index("<svg"); end=html.index("</svg>",start)+len("</svg>")
   self.assertEqual(html[start:end],source); self.assertNotIn("<script src=",html)
   self.assertNotRegex(html,r'href=["\']https?://')
 def test_pinned_official_icons_are_embedded(self):
  self.assertEqual(PROVENANCE["official_icon_catalog"],"https://cloud.google.com/icons")
  self.assertEqual(PROVENANCE["source_commit"],"9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192")
  self.assertEqual(PROVENANCE["cloud_verification"],"not-run")
  embedded=[]
  for source in (SOLUTION,FLOW): embedded.extend(base64.b64decode(v) for v in re.findall(r'data:image/svg\+xml;base64,([^"]+)',source))
  for filename,item in PROVENANCE["icons"].items():
   icon=(ROOT/item["path"]).read_bytes(); blob=b"blob "+str(len(icon)).encode("ascii")+b"\x00"+icon
   self.assertEqual(hashlib.sha1(blob).hexdigest(),item["git_blob_sha"],filename); self.assertIn(icon,embedded,filename)
 def test_personal_custom_palette_scopes_and_relationships(self):
  root=ET.fromstring(SOLUTION); ids={n.attrib.get("id") for n in root.iter()}
  for item in ("project-scope","region-scope","customer-vpc","legacy-backend","cloud-run-backend","target-database","secret-manager","url-map","url-map-to-legacy","url-map-to-run","run-to-sql","source-cloud-nat","source-to-cloud-nat","source-nat-to-internet"):
   self.assertIn(item,ids)
  for color in ("#F7FAFF","#EFF6FF","#F0FDFA","#FFF7ED","#F5F3FF","#F1F5F9"): self.assertIn(color,SOLUTION)
  labels=" ".join(n.text or "" for n in root.iter() if n.tag.endswith("text"))
  for label in ("asia-southeast1","10.80.0.0/24","10.80.1.0/26","Private IP via PSA","one active backend at a time","unmanaged instance group","Serverless NEG"):
   self.assertIn(label.lower(),labels.lower())
 def test_source_subnet_has_scoped_nat_egress(self):
  root=ET.fromstring(SOLUTION); ids={n.attrib.get("id") for n in root.iter()}
  self.assertIn("icon-cloud_nat",ids)
  labels=" ".join(n.text or "" for n in root.iter() if n.tag.endswith("text"))
  self.assertIn("Cloud NAT",labels); self.assertIn("outbound bootstrap egress",labels)
  self.assertIn("10.80.0.0/24",labels); self.assertIn("no public IP",labels)
 def test_routes_are_orthogonal_and_migration_backout_is_explicit(self):
  root=ET.fromstring(SOLUTION); paths={n.attrib.get("id"):n for n in root.iter() if n.tag.endswith("path") and n.attrib.get("id")}
  for key in ("url-map-to-legacy","url-map-to-run","run-to-sql","secret-to-run"):
   self.assertIn(key,paths); self.assertNotRegex(paths[key].attrib["d"],r"[CQST]")
  flowroot=ET.fromstring(FLOW); ids={n.attrib.get("id") for n in flowroot.iter()}
  for key in ("baseline-lane","freeze-step","transfer-step","reconcile-step","cutover-step","dms-change-request","dms-cdc","dms-promote","rollback-boundary"): self.assertIn(key,ids)
  self.assertIn("ก่อน target รับ writes",FLOW); self.assertIn("หลัง target รับ writes",FLOW)
 def test_readme_embeds_design_and_does_not_claim_cloud_pass(self):
  readme=(ROOT/"README.md").read_text(encoding="utf-8")
  self.assertIn("assets/solution.svg",readme); self.assertIn("assets/migration-flow.svg",readme)
  self.assertIn("Cloud verification:** Not run",readme)
  self.assertNotRegex(readme.lower(),r"cloud[- ]verified\s*[:=]\s*pass")
if __name__=="__main__": unittest.main()
