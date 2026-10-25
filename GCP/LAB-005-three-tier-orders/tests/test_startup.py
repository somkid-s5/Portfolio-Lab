"""Exercise embedded startup Python without metadata or root access."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
SHELL=(ROOT/'scripts/startup.sh').read_text()
SOURCE=SHELL.split("<<'LAB005_PY'\n",1)[1].rsplit('\nLAB005_PY',1)[0]
MODULE={'__name__':'startup_contract'}
exec(compile(SOURCE,'startup.sh:python','exec'),MODULE)

class StartupTests(unittest.TestCase):
    def encode(self,value):
        return base64.b64encode(json.dumps(value).encode())

    def test_shell_and_python_syntax(self):
        subprocess.run(['bash','-n',str(ROOT/'scripts/startup.sh')],check=True,capture_output=True)
        compile(SOURCE,'startup.sh:python','exec')

    def test_exact_files_and_bounds(self):
        valid={'release.py':'VALUE=1\n','vm-install.py':'VALUE=2\n'}
        self.assertEqual(set(MODULE['decode_bundle'](self.encode(valid))),set(valid))
        for value in [{}, {'../escape':'pass'}, {**valid,'secret.json':'value'},
                      {**valid,'release.py':42},{**valid,'release.py':'x'*100001},
                      {**valid,'release.py':'def broken('}]:
            with self.assertRaises((ValueError,SyntaxError)):
                MODULE['decode_bundle'](self.encode(value))
        with self.assertRaises(ValueError):
            MODULE['decode_bundle'](b'x'*262145)

    def test_private_staging_and_bounded_child(self):
        with tempfile.TemporaryDirectory() as parent:
            calls=[]
            def fake_run(args,**kwargs):
                calls.append((args,kwargs))
                directory=Path(args[1]).parent
                self.assertEqual(directory.stat().st_mode&0o777,0o700)
                for name in ('release.py','vm-install.py'):
                    self.assertEqual((directory/name).stat().st_mode&0o777,0o600)
                self.assertNotIn('PGPASSWORD',kwargs['env'])
                self.assertEqual(kwargs['timeout'],900)
                return SimpleNamespace(returncode=2)
            code=MODULE['launch']({'release.py':b'pass','vm-install.py':b'pass'},parent, fake_run)
            self.assertEqual(code,2)
            self.assertEqual(len(calls),1)

if __name__=='__main__':
    unittest.main()
