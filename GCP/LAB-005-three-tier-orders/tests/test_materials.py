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
