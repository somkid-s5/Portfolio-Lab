import hashlib
import json
import os
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
from werkzeug.security import check_password_hash

ROOT=Path(__file__).resolve().parents[1]

class MaterialsTests(unittest.TestCase):
    def test_secret_bundle_hashes_permissions_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'secrets'
            command=[sys.executable,str(ROOT/'scripts/create-secrets.py'),'--out',str(target)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            auth=json.loads((target/'auth.json').read_text())
            logins=json.loads((target/'demo-logins.json').read_text())
            self.assertGreaterEqual(len(auth['session_key']),64)
            for name,password in logins.items():
                self.assertTrue(check_password_hash(auth['users'][name]['password_hash'],password))
                self.assertNotIn(password,result.stdout+result.stderr)
            admin=json.loads((target/'bootstrap-admin.json').read_text())
            self.assertEqual(admin['user'],'postgres')
            self.assertEqual(admin['database'],'booking')
            self.assertEqual(admin['password'],(target/'sql-admin-password.txt').read_text().strip())
            self.assertNotIn(admin['password'],result.stdout+result.stderr)
            self.assertNotEqual(admin['password'],json.loads((target/'db-a.json').read_text())['password'])
            snapshot={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()}
            old=(target/'db-a.json').read_bytes()
            self.assertNotEqual(json.loads(old)['password'],json.loads((target/'db-b.json').read_text())['password'])
            if os.name=='posix':
                self.assertEqual(target.stat().st_mode & 0o777,0o700)
                for path in target.iterdir():
                    self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertNotEqual(subprocess.run(command,capture_output=True,text=True,timeout=5).returncode,0)
            self.assertEqual((target/'db-a.json').read_bytes(),old)
            self.assertEqual(snapshot,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()})

    def test_all_python_materials_compile(self):
        for folder in ['app','scripts','tests']:
            for path in (ROOT/folder).glob('*.py'):
                py_compile.compile(str(path),doraise=True)

if __name__=='__main__':
    unittest.main(verbosity=2)
