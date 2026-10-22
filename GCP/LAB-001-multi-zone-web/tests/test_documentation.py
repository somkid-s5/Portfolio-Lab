"""Validate Lab 01 documentation links and its SVG without cloud resources."""
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

class DocumentationTests(unittest.TestCase):
    def test_relative_links_and_anchors(self):
        text = (ROOT / 'README.md').read_text()
        text = re.sub(r'```[\\s\\S]*?```', '', text)
        headings = re.findall(r'^#{1,6} (.+)$', text, re.M)
        anchors = {re.sub(r'[^\\w\\- ]', '', h.lower()).replace(' ', '-') for h in headings}
        for target in re.findall(r'!?\\[[^\\]]*\\]\\(([^)]+)\\)', text):
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
