"""Installer contracts only; no GCE calls, apt or systemd execution."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('vm_install',ROOT/'scripts/vm-install.py')
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def test_crc32c_and_environment_references(self):
        self.assertEqual(installer.crc32c(b'123456789'),0xe3069283)
        self.assertEqual(installer.crc32c(b''),0)
        self.assertEqual(installer.env_text({'DB_MODE':'cloud'}),'DB_MODE=cloud\n')
        for value in ['x\nPASSWORD=bad','a b','$(touch /tmp/bad)','"quoted"']:
            with self.assertRaises(ValueError):
                installer.env_text({'DB_CONFIG_FILE':value})

    def test_identity_and_numeric_versions_before_artifact(self):
        class Cloud:
            def __init__(self):
                self.values={
                    'instance/attributes/lab005-managed':'true',
                    'instance/attributes/lab005-tier':'api',
                    'project/project-id':'test-project',
                    'instance/service-accounts/default/email':'lab005-api@test-project.iam.gserviceaccount.com',
                    'instance/attributes/lab005-artifact-bucket':'test-bucket',
                    'instance/attributes/lab005-artifact-sha256':'a'*64,
                    'instance/attributes/lab005-sql-instance':'test-project:asia-southeast1:lab005-sql',
                    'instance/attributes/lab005-db-version':'1',
                    'instance/attributes/lab005-auth-version':'2'}
            def metadata(self,key):
                return self.values[key]
            def artifact(self,*args):
                raise AssertionError('Must reject before artifact access')
        cloud=Cloud()
        self.assertEqual(installer.settings(cloud)['auth_version'],'2')
        cloud.values['instance/attributes/lab005-db-version']='latest'
        with self.assertRaises(ValueError):
            installer.install(cloud)
        cloud.values['instance/attributes/lab005-db-version']='1'
        cloud.values['instance/service-accounts/default/email']='default@test-project.iam.gserviceaccount.com'
        with self.assertRaises(ValueError):
            installer.install(cloud)

    def test_existing_release_and_atomic_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            release=root/'release'
            release.mkdir()
            (release/'file').write_bytes(b'expected')
            installer.verify_existing(release,{'file':b'expected'})
            (release/'file').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                installer.verify_existing(release,{'file':b'expected'})
            private=root/'private.json'
            installer.atomic(private,b'private-value',0o600,os.getuid(),os.getgid())
            self.assertEqual(private.stat().st_mode&0o777,0o600)
            link=root/'linked'
            link.symlink_to(private)
            with self.assertRaises(ValueError):
                installer.atomic(link,b'overwrite',uid=os.getuid(),gid=os.getgid())
            self.assertEqual(private.read_bytes(),b'private-value')

    def test_main_sanitizes_secret_bearing_failure(self):
        output=io.StringIO()
        with patch.object(installer.os,'geteuid',side_effect=RuntimeError('PASSWORD-NEVER-PRINT')),contextlib.redirect_stderr(output):
            self.assertEqual(installer.main(),2)
        self.assertNotIn('PASSWORD-NEVER-PRINT',output.getvalue())
        self.assertIn('RuntimeError',output.getvalue())

    def test_unit_references_files_not_secret_payload(self):
        unit=installer.api_unit('/opt/lab005/releases/hash','/opt/lab005/venvs/hash','/etc/lab005/api.env')
        self.assertIn('User=lab005-api',unit)
        self.assertIn('EnvironmentFile=/etc/lab005/api.env',unit)
        self.assertIn('--workers 1 --threads 8',unit)
        self.assertIn('ProtectSystem=strict',unit)
        self.assertNotIn('password',unit.lower())

if __name__=='__main__':
    unittest.main()
