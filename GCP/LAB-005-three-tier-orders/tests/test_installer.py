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

class InstallerSandboxTests(unittest.TestCase):
    """Real archive/filesystem execution; metadata, packages and services are fakes."""
    def fixture(self,role):
        import json
        import release
        tier='api' if role=='init' else role
        files={name:(ROOT/name).read_bytes() for name in release.LAYOUT[tier]}
        metadata={'schema':1,'lab':'LAB-005','tier':tier,'source_commit':'b'*40,'app_version':'v1',
                  'files':[{'path':p,'size':len(v),'sha256':release.digest(v)} for p,v in sorted(files.items())]}
        files['release.json']=release.json_bytes(metadata)
        archive=release.archive_bytes(files)
        checksum=release.digest(archive)
        class FakeCloud:
            def __init__(self):
                sa='bootstrap' if role=='init' else role
                self.calls=[]
                self.archive=archive
                self.values={
                    'instance/attributes/lab005-managed':'true',
                    'instance/attributes/lab005-tier':role,
                    'project/project-id':'test-project',
                    'instance/service-accounts/default/email':f'lab005-{sa}@test-project.iam.gserviceaccount.com',
                    'instance/attributes/lab005-artifact-bucket':'test-bucket',
                    'instance/attributes/lab005-artifact-sha256':checksum,
                    'instance/attributes/lab005-sql-instance':'test-project:asia-southeast1:lab005-sql',
                    'instance/attributes/lab005-api-vip':'10.55.20.10',
                    'instance/attributes/lab005-db-version':'1',
                    'instance/attributes/lab005-auth-version':'2',
                    'instance/attributes/lab005-admin-version':'3'}
            def metadata(self,name):
                return self.values[name]
            def artifact(self,bucket,digest,tier_name):
                self.calls.append(('artifact',bucket,digest,tier_name))
                return self.archive
            def secret(self,project,name,version):
                self.calls.append(('secret',name,version))
                values={
                    'lab005-db':{'user':'orders_app','database':'orders','password':'R'*40},
                    'lab005-bootstrap-admin':{'user':'postgres','database':'orders','password':'A'*40},
                    'lab005-auth':{'session_key':'S'*64,'users':{'alice':{'role':'customer','password_hash':'fixture-only'}}}}
                return json.dumps(values[name]).encode()
        return FakeCloud(),checksum

    def execute(self,cloud,root):
        from types import SimpleNamespace
        calls=[]
        live=[]
        def run(args,**kwargs):
            calls.append((args,kwargs))
            if args[:3]==['python3','-m','venv']:
                Path(args[3]).mkdir(parents=True)
            return SimpleNamespace(returncode=0)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            installer.install(cloud,root=root,run=run,
                              account=SimpleNamespace(pw_gid=os.getgid()),
                              waiter=live.append,owner_uid=os.getuid(),owner_gid=os.getgid())
        self.assertNotIn('R'*40,output.getvalue())
        self.assertNotIn('A'*40,output.getvalue())
        self.assertNotIn('S'*64,output.getvalue())
        return calls,live

    def test_web_reuses_verified_bundle_without_secret_access_or_pycache(self):
        cloud,checksum=self.fixture('web')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            calls,live=self.execute(cloud,root)
            self.assertEqual(live,[80])
            self.assertFalse(any(call[0]=='secret' for call in cloud.calls))
            self.assertIn((['systemctl','restart','nginx'],{}),calls)
            active=root/'etc/nginx/nginx.conf'
            self.assertIn('10.55.20.10:8080',active.read_text())
            self.execute(cloud,root)
            self.assertFalse(list((root/'opt/lab005/releases'/checksum).rglob('__pycache__')))
            (root/'opt/lab005/releases'/checksum/'web/app.js').write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                self.execute(cloud,root)

    def test_api_private_configs_and_no_admin_secret(self):
        cloud,checksum=self.fixture('api')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            calls,live=self.execute(cloud,root)
            self.assertEqual(live,[8080])
            self.assertEqual([call[1] for call in cloud.calls if call[0]=='secret'],['lab005-db','lab005-auth'])
            env=root/'etc/lab005/api.env'
            self.assertEqual(env.stat().st_mode&0o777,0o600)
            credentials=root/'var/lib/lab005'/('api-'+checksum)
            for name in ('db.json','auth.json'):
                self.assertEqual((credentials/name).stat().st_mode&0o777,0o640)
            unit=(root/'etc/systemd/system/lab005-api.service').read_text()
            safe=env.read_text()+unit+repr(calls)
            for secret in ('R'*40,'S'*64):
                self.assertNotIn(secret,safe)
            self.assertIn('AUTH_CONFIG_FILE=',safe)
            self.assertNotIn('init-db.py',repr(calls))

    def test_bootstrap_uses_admin_file_without_runtime_service(self):
        cloud,checksum=self.fixture('init')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            calls,live=self.execute(cloud,root)
            self.assertEqual(live,[])
            self.assertEqual([call[1] for call in cloud.calls if call[0]=='secret'],['lab005-db','lab005-bootstrap-admin'])
            bootstrap=[call for call in calls if any(arg.endswith('/scripts/init-db.py') for arg in call[0])]
            self.assertEqual(len(bootstrap),1)
            self.assertTrue(bootstrap[0][1]['env']['DB_CONFIG_FILE'].endswith('/admin.json'))
            self.assertNotIn('PGPASSWORD',bootstrap[0][1]['env'])
            self.assertFalse(any(call[0][0]=='systemctl' for call in calls))
            credentials=root/'var/lib/lab005'/('init-'+checksum)
            self.assertEqual(credentials.stat().st_mode&0o777,0o700)
            for name in ('db.json','admin.json'):
                self.assertEqual((credentials/name).stat().st_mode&0o777,0o600)
            self.assertNotIn('A'*40,repr(calls))

    def test_bad_archive_stops_before_package_or_secret_calls(self):
        cloud,_=self.fixture('api')
        cloud.archive=b'corrupt'
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                self.execute(cloud,Path(directory))
            self.assertEqual(list(Path(directory).iterdir()),[])
            self.assertFalse(any(call[0]=='secret' for call in cloud.calls))

if __name__=='__main__':
    unittest.main()
