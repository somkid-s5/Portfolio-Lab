from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('docs_builder',ROOT/'scripts/build-release.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

class ProbeTests(unittest.TestCase):
    def exercise(self,release,cache_wrong=False):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'release'
            manifest=builder.build(release,output)
            metadata={f['path']:f['cache_control'] for f in manifest['files']}
            class Fixture(SimpleHTTPRequestHandler):
                def log_message(self,*args):
                    pass
                def end_headers(self):
                    path=urlsplit(self.path).path.lstrip('/')
                    if path in metadata:
                        self.send_header('Cache-Control','no-store' if cache_wrong else metadata[path])
                    super().end_headers()
            server=ThreadingHTTPServer(('127.0.0.1',0),partial(Fixture,directory=str(output)))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            target=Path(tmp)/'evidence.json'
            command=[sys.executable,str(ROOT/'scripts/probe-release.py'),
                '--url',f'http://127.0.0.1:{server.server_port}','--allow-local-http',
                '--manifest',str(output/'manifest.json'),'--requests','2','--out',str(target)]
            try:
                result=subprocess.run(command,capture_output=True,text=True,timeout=10)
                evidence=json.loads(target.read_text())
                original=target.read_bytes()
                again=subprocess.run(command,capture_output=True,text=True,timeout=10)
                self.assertNotEqual(again.returncode,0)
                self.assertEqual(target.read_bytes(),original)
                return result,evidence
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_good_content_and_metadata_with_real_http(self):
        result,evidence=self.exercise('v1')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(evidence['all_checks_passed'])
        self.assertFalse(evidence['tls_verified'])
        self.assertEqual(len(evidence['results']),3)
        self.assertTrue(all('?' not in row['url'] for row in evidence['results']))

    def test_bad_semantics_fails_even_when_hashes_match(self):
        result,evidence=self.exercise('bad')
        self.assertEqual(result.returncode,1)
        self.assertFalse(evidence['all_checks_passed'])
        self.assertTrue(all(row['content_match'] for row in evidence['results']))
        self.assertFalse(evidence['results'][0]['business_content_ok'])

    def test_wrong_cache_metadata_fails(self):
        result,evidence=self.exercise('v2',True)
        self.assertEqual(result.returncode,1)
        self.assertFalse(evidence['results'][0]['cache_policy_match'])

if __name__=='__main__':
    unittest.main(verbosity=2)
