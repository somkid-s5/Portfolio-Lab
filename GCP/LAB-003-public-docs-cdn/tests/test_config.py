import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('lab003_config',ROOT/'scripts/render-config.py')
config=importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)

class URLMapTests(unittest.TestCase):
    def test_global_content_and_http_redirect_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'config'
            maps=config.render('training-project','docs.example.com',out)
            content=maps['content-map.json']
            self.assertTrue(content['defaultService'].endswith('/global/backendBuckets/lab003-docs-backend'))
            rule=content['pathMatchers'][0]['pathRules'][0]
            self.assertEqual(rule['paths'],['/'])
            self.assertEqual(rule['urlRedirect']['pathRedirect'],'/index.html')
            self.assertNotIn('httpsRedirect',rule['urlRedirect'])
            self.assertTrue(maps['http-redirect-map.json']['defaultUrlRedirect']['httpsRedirect'])
            with self.assertRaises(FileExistsError):
                config.render('training-project','docs.example.com',out)

    def test_rejects_urls_and_invalid_project_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            for project,host in [('bad;project','docs.example.com'),
                                 ('training-project','https://docs.example.com'),
                                 ('training-project','docs.example.com/extra')]:
                with self.assertRaises(ValueError):
                    config.render(project,host,Path(tmp)/'out')

if __name__=='__main__':
    unittest.main(verbosity=2)
