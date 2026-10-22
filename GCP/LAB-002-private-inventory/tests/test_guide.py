import re
from pathlib import Path
import subprocess
import unittest

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
