import py_compile
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class GuideTests(unittest.TestCase):
    def test_links_and_task_navigation(self):
        text=(ROOT/'README.md').read_text()
        clean=re.sub(r'```[\s\S]*?```','',text)
        ids=set(re.findall(r'<a id="([^"]+)"',clean))
        self.assertEqual(ids,{f'task-{i}' for i in range(12)})
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',clean):
            if '://' in target:
                continue
            path,_,anchor=target.partition('#')
            if path:
                self.assertTrue((ROOT/path).exists(),target)
            elif anchor:
                self.assertIn(anchor,ids,target)

    def test_shell_blocks_parse_without_execution(self):
        blocks=re.findall(r'```bash\n([\s\S]*?)```',(ROOT/'README.md').read_text())
        self.assertGreaterEqual(len(blocks),15)
        for index,block in enumerate(blocks):
            run=subprocess.run(['bash','-n'],input=block,text=True,capture_output=True,timeout=5)
            self.assertEqual(run.returncode,0,f'block {index}: {run.stderr}')

    def test_materials_compile_and_cloud_state_is_honest(self):
        for folder in ['scripts','tests']:
            for path in (ROOT/folder).glob('*.py'):
                py_compile.compile(str(path),doraise=True)
        text=(ROOT/'README.md').read_text()
        self.assertIn('cloud_verification: not-run',text)
        self.assertIn('EXTERNAL_MANAGED',text)
        self.assertNotIn('--load-balancing-scheme=EXTERNAL ',text)

if __name__=='__main__':
    unittest.main(verbosity=2)
