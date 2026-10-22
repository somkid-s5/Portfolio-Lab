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

    def test_deploy_is_dry_run_and_pins_identity_network_and_secrets(self):
        cmd=[sys.executable,str(ROOT/'scripts/deploy-service.py'),'--project','sandbox-booking',
             '--image','asia-southeast1-docker.pkg.dev/sandbox-booking/lab004-images/booking@sha256:'+'a'*64,
             '--auth-version','1','--db-version','2','--suffix','v1-a01']
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        for expected in ['DRY RUN','lab004-runtime@','private-ranges-only','--max-instances 2',
                         'lab004-db-a:2','lab004-auth:1','APP_VERSION=v1','/livez']:
            self.assertIn(expected,result.stdout)
        self.assertNotIn('APP_LOCAL_TEST',result.stdout)
        self.assertNotIn('bootstrap-admin',result.stdout)
        candidate=subprocess.run(cmd+['--candidate','--login','b','--concurrency','16'],
                                 capture_output=True,text=True,timeout=5)
        self.assertEqual(candidate.returncode,0,candidate.stderr)
        self.assertIn('--no-traffic --tag candidate',candidate.stdout)
        self.assertIn('lab004-db-b:2',candidate.stdout)
        for flags in [['--db-version','latest'],['--image','untrusted/image:v1'],
                      ['--concurrency','100'],['--suffix','invalid_suffix']]:
            rejected=subprocess.run(cmd+flags,capture_output=True,text=True,timeout=5)
            self.assertNotEqual(rejected.returncode,0)


    def test_runtime_secret_boundary_probe_does_not_read_or_log_payload(self):
        import importlib.util
        from unittest.mock import Mock
        spec=importlib.util.spec_from_file_location('secret_boundary',ROOT/'scripts/check-secret-boundary.py')
        from google.auth.transport.requests import AuthorizedSession
        checker=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        response=Mock(status_code=403)
        session=Mock()
        session.get.return_value=response
        self.assertTrue(checker.check(session,'sandbox-booking','1')['denied'])
        response.json.assert_not_called()
        response.close.assert_called_once()
        for status in [200,401,404,500]:
            response=Mock(status_code=status)
            session.get.return_value=response
            with self.assertRaisesRegex(ValueError,'Expected permission denied'):
                checker.check(session,'sandbox-booking','1')
            response.json.assert_not_called()
            response.close.assert_called_once()
        with self.assertRaises(ValueError):
            checker.check(session,'sandbox-booking','latest')


    def test_guide_task_links_and_shell_syntax(self):
        import re
        from urllib.parse import unquote,urlsplit
        guide=(ROOT/'README.md').read_text()
        for task in range(13):
            self.assertIn('### Task '+str(task)+' —',guide)
        for requirement in range(1,9):
            self.assertIn('| R'+str(requirement)+' ',guide)
        for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',guide):
            parsed=urlsplit(link)
            if parsed.scheme or link.startswith('#'):
                continue
            path=unquote(parsed.path)
            self.assertTrue((ROOT/path).exists(),'Missing relative guide link: '+path)
        fences=re.findall(r'```bash\n(.*?)```',guide,re.S)
        self.assertGreaterEqual(len(fences),20)
        for index,script in enumerate(fences):
            result=subprocess.run(['bash','-n'],input=script,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,'Bash block '+str(index)+': '+result.stderr)


    def test_bootstrap_entrypoint_hides_secret_bearing_sql_errors(self):
        import contextlib
        import importlib.util
        import io
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location('booking_bootstrap',ROOT/'scripts/init-db.py')
        bootstrap=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        for error in [RuntimeError('CREATE ROLE PASSWORD ci-only-sensitive-marker'),
                      ValueError('untrusted ci-only-sensitive-marker')]:
            output=io.StringIO()
            with patch.object(bootstrap,'main',side_effect=error),contextlib.redirect_stderr(output):
                code=bootstrap.run()
            self.assertEqual(code,2)
            self.assertNotIn('ci-only-sensitive-marker',output.getvalue())
            self.assertNotIn('CREATE ROLE PASSWORD',output.getvalue())
        output=io.StringIO()
        with patch.object(bootstrap,'main',side_effect=ValueError('Runtime role exists; stop and inspect instead of resetting a live password')),contextlib.redirect_stderr(output):
            self.assertEqual(bootstrap.run(),2)
        self.assertIn('Runtime role exists',output.getvalue())

    def test_all_python_materials_compile(self):
        for folder in ['app','scripts','tests']:
            for path in (ROOT/folder).glob('*.py'):
                py_compile.compile(str(path),doraise=True)

if __name__=='__main__':
    unittest.main(verbosity=2)
