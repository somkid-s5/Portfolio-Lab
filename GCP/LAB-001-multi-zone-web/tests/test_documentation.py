"""Validate Lab 01 documentation links and its SVG without cloud resources."""
from pathlib import Path
import re
import unittest
import unicodedata
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

class DocumentationTests(unittest.TestCase):
    def test_relative_links_and_anchors(self):
        text = (ROOT / 'README.md').read_text()
        text = re.sub(r'```[\s\S]*?```', '', text)
        headings = re.findall(r'^#{1,6} (.+)$', text, re.M)
        anchors = {''.join(c for c in h.lower() if c.isalnum() or c in '_- ' or unicodedata.category(c).startswith('M')).replace(' ', '-') for h in headings}
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', text):
            if '://' in target or target.startswith('mailto:'):
                continue
            path, _, anchor = target.partition('#')
            if path:
                self.assertTrue((ROOT / path).exists(), target)
            elif anchor:
                self.assertIn(anchor, anchors, target)

    def test_no_stale_test_lab_names(self):
        guide = (ROOT / 'README.md').read_text()
        self.assertNotIn('lab2', guide)
        self.assertNotIn('LAB-TEST', guide)
        self.assertIn('cloud_verification: not-run', guide)
        for task in range(11):
            self.assertIn(f'## Task {task} ', guide)
        self.assertIn('## Task 8B ', guide)

    def test_changed_diagram_has_all_backend_ids(self):
        text = (ROOT / 'assets/solution-after-change.svg').read_text()
        ET.fromstring(text)
        for backend in ['a', 'b', 'c']:
            self.assertIn(f'lab001-app-{backend}', text)
            self.assertIn(f'lab001-group-{backend}', text)
        self.assertIn('asia-southeast1-a', text)

    def test_accessible_offline_svg(self):
        tree = ET.parse(ROOT / 'assets/solution.svg')
        root = tree.getroot()
        self.assertEqual(root.attrib['role'], 'img')
        ns = {'s': 'http://www.w3.org/2000/svg'}
        self.assertIsNotNone(root.find('s:title', ns))
        self.assertIsNotNone(root.find('s:desc', ns))
        for node in root.iter():
            for key, value in node.attrib.items():
                if key.endswith('href'):
                    self.assertFalse(value.startswith(('http:', 'https:')), value)

if __name__ == '__main__':
    unittest.main(verbosity=2)
