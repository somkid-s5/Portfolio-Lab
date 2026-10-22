import importlib.util
from pathlib import Path
import py_compile
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class MaterialsTests(unittest.TestCase):
    def test_web_config_syntax_and_rejected_injection(self):
        spec=importlib.util.spec_from_file_location('web_config',ROOT/'scripts/render-web-config.py')
        renderer=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            config=root/'nginx.conf'
            config.write_text(renderer.render('127.0.0.1',str(ROOT/'web'),18080,18081,True,
                                             str(root/'nginx.pid'),str(root)))
            result=subprocess.run(['nginx','-t','-p',str(root)+'/',
                                   '-c',str(config)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            source=config.read_text()
            self.assertNotIn('{{',source)
            self.assertIn('proxy_next_upstream off;',source)
            self.assertIn('X-Forwarded-Proto https',source)
            self.assertIn('pid '+str(root/'nginx.pid')+';',source)
        for vip in ['8.8.8.8','127.0.0.1','10.55.10.10','10.55.20.10;return 200']:
            with self.assertRaises(ValueError):
                renderer.render(vip,'/opt/lab005/web/current')
        with self.assertRaises(ValueError):
            renderer.render('10.55.20.10','/tmp/bad;root /')
        with self.assertRaises(ValueError):
            renderer.render('10.55.20.10','/opt/lab005/web/current',api_port=5432)


    def test_secret_bundle_hashes_permissions_and_no_overwrite(self):
        import hashlib
        import json
        import os
        import sys
        from werkzeug.security import check_password_hash
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'secrets'
            cmd=[sys.executable,str(ROOT/'scripts/create-secrets.py'),'--out',str(target)]
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0)
            auth=json.loads((target/'auth.json').read_text())
            logins=json.loads((target/'demo-logins.json').read_text())
            runtime=json.loads((target/'db.json').read_text())
            admin=json.loads((target/'bootstrap-admin.json').read_text())
            self.assertEqual(runtime['user'],'orders_app')
            self.assertEqual(runtime['database'],'orders')
            self.assertEqual(admin['user'],'postgres')
            self.assertEqual(admin['password'],(target/'sql-admin-password.txt').read_text().strip())
            self.assertFalse(admin['password']==runtime['password'])
            self.assertGreaterEqual(len(auth['session_key']),64)
            for user,password in logins.items():
                self.assertTrue(check_password_hash(auth['users'][user]['password_hash'],password))
                self.assertFalse(password in result.stdout+result.stderr)
            self.assertEqual(auth['users']['alice']['role'],'customer')
            self.assertEqual(auth['users']['operator']['role'],'operator')
            self.assertFalse(runtime['password'] in result.stdout+result.stderr)
            self.assertFalse(admin['password'] in result.stdout+result.stderr)
            snapshot={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()}
            if os.name=='posix':
                self.assertEqual(target.stat().st_mode&0o777,0o700)
                for path in target.iterdir():
                    self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertNotEqual(subprocess.run(cmd,capture_output=True,timeout=5).returncode,0)
            self.assertEqual(snapshot,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()})

    def test_bootstrap_suppresses_secret_bearing_exception(self):
        import contextlib
        import io
        import json
        import os
        from unittest.mock import Mock,patch
        spec=importlib.util.spec_from_file_location('bootstrap_cli',ROOT/'scripts/init-db.py')
        bootstrap=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            runtime=root/'runtime.json'
            admin=root/'admin.json'
            runtime.write_text(json.dumps({'user':'orders_app','database':'orders','password':'r'*40}))
            admin.write_text(json.dumps({'user':'postgres','database':'orders','password':'a'*40}))
            engine=Mock()
            stdout,stderr=io.StringIO(),io.StringIO()
            with patch('sys.argv',['init-db.py','--runtime-file',str(runtime)]), patch.dict(os.environ,{'DB_CONFIG_FILE':str(admin)}), patch.object(bootstrap,'create_pool',return_value=engine), patch.object(bootstrap,'initialize',side_effect=RuntimeError('CREATE ROLE PASSWORD '+('r'*40))), contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                code=bootstrap.main()
            self.assertEqual(code,2)
            output=stdout.getvalue()+stderr.getvalue()
            self.assertFalse('r'*40 in output)
            self.assertNotIn('CREATE ROLE PASSWORD',output)
            self.assertIn('RuntimeError',output)
            engine.dispose.assert_called_once()

    def test_python_compiles_and_ui_has_no_inline_execution(self):
        for folder in ['app','scripts','tests']:
            for path in (ROOT/folder).glob('*.py'):
                py_compile.compile(str(path),doraise=True)
        html=(ROOT/'web/index.html').read_text()
        for attribute in ['onclick=','onload=','javascript:']:
            self.assertNotIn(attribute,html.lower())
        self.assertIn('src="/app.js"',html)
        js=(ROOT/'web/app.js').read_text()
        self.assertNotIn('innerHTML',js)
        self.assertNotIn('localStorage',js)
        self.assertIn('sessionStorage',js)

if __name__=='__main__':
    unittest.main(verbosity=2)
