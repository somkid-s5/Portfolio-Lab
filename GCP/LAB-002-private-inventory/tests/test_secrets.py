import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class SecretBundleTests(unittest.TestCase):
    def test_bundle_permissions_hashes_no_output_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'secrets'
            command=[sys.executable,str(ROOT/'scripts/create-secrets.py'),'--out',str(target)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            hashes=json.loads((target/'token-hashes.json').read_text())
            for role in ['reader','operator']:
                token=(target/(role+'.token')).read_text().strip()
                self.assertGreaterEqual(len(token),40)
                self.assertEqual(hashlib.sha256(token.encode()).hexdigest(),hashes[role])
                self.assertNotIn(token,result.stdout+result.stderr)
            original=(target/'db-password.txt').read_bytes()
            self.assertNotIn(original.decode().strip(),result.stdout+result.stderr)
            if os.name=='posix':
                self.assertEqual(target.stat().st_mode & 0o777,0o700)
                for path in target.iterdir():
                    self.assertEqual(path.stat().st_mode & 0o777,0o600)
            again=subprocess.run(command,capture_output=True,text=True,timeout=5)
            self.assertNotEqual(again.returncode,0)
            self.assertEqual((target/'db-password.txt').read_bytes(),original)

if __name__=='__main__':
    unittest.main(verbosity=2)
