import re
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET
import py_compile

ROOT=Path(__file__).resolve().parents[1]

class GuideTests(unittest.TestCase):
    def test_links_and_explicit_navigation(self):
        text=(ROOT/'README.md').read_text()
        clean=re.sub(r'```[\s\S]*?```','',text)
        ids=set(re.findall(r'<a id="([^"]+)"',clean))
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',clean):
            if '://' in target:
                continue
            path,_,anchor=target.partition('#')
            if path:
                self.assertTrue((ROOT/path).exists(),target)
            elif anchor:
                self.assertIn(anchor,ids,target)
        self.assertEqual({f'task-{i}' for i in range(13)},ids)

    def test_shell_blocks_parse_without_running(self):
        text=(ROOT/'README.md').read_text()
        blocks=re.findall(r'```bash\n([\s\S]*?)```',text)
        self.assertGreaterEqual(len(blocks),15)
        for index,block in enumerate(blocks):
            result=subprocess.run(['bash','-n'],input=block,text=True,
                                  capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,f'block {index}: {result.stderr}')

    def test_all_python_materials_compile(self):
        for folder in ['app','scripts','tests']:
            for path in (ROOT/folder).glob('*.py'):
                py_compile.compile(str(path),doraise=True)

    def test_both_diagrams_are_accessible_offline(self):
        for filename in ['solution.svg','operations.svg']:
            root=ET.parse(ROOT/'assets'/filename).getroot()
            self.assertEqual(root.attrib['role'],'img')
            ns={'s':'http://www.w3.org/2000/svg'}
            self.assertIsNotNone(root.find('s:title',ns))
            self.assertIsNotNone(root.find('s:desc',ns))
            for element in root.iter():
                for key,value in element.attrib.items():
                    if key.endswith('href'):
                        self.assertFalse(value.startswith(('http:','https:')))

    def test_no_fake_cloud_results(self):
        text=(ROOT/'README.md').read_text()
        self.assertIn('cloud_verification: not-run',text)
        for i in range(13):
            self.assertIn(f'## Task {i} ',text)
        for i in range(1,9):
            self.assertIn(f'R{i}',text)
        self.assertNotIn('lab001-',text)

if __name__=='__main__':
    unittest.main(verbosity=2)
