import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
def module(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result
builder=module('lab003_build','build-release.py')
publisher=module('lab003_publish','publish-release.py')

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.work=Path(self.tmp.name)
        self.out=self.work/'v1'
        builder.build('v1',self.out)

    def tearDown(self):
        self.tmp.cleanup()

    def test_deterministic_manifest_and_hashed_asset(self):
        second=self.work/'again'
        builder.build('v1',second)
        self.assertEqual((self.out/'manifest.json').read_bytes(),(second/'manifest.json').read_bytes())
        _,manifest=publisher.load_release(self.out)
        for entry in manifest['files']:
            self.assertEqual(hashlib.sha256((self.out/entry['path']).read_bytes()).hexdigest(),entry['sha256'])
        with self.assertRaises(FileExistsError):
            builder.build('v1',self.out)

    def test_html_ttl_can_change_without_renaming_assets(self):
        fast=self.work/'fast'
        builder.build('v1',fast,15)
        _,manifest=publisher.load_release(fast)
        self.assertEqual((self.out/'index.html').read_bytes(),(fast/'index.html').read_bytes())
        index=next(e for e in manifest['files'] if e['path']=='index.html')
        self.assertEqual(index['cache_control'],'public,max-age=15')
        _,plan=publisher.commands(fast,'lab003-example-docs','100',True)
        self.assertIn('--cache-control=public,max-age=15',plan[-1]['command'])
        with self.assertRaises(ValueError):
            builder.build('v1',self.work/'unsafe',9999)

    def test_v2_and_bad_are_distinct(self):
        for release in ['v2','bad']:
            out=self.work/release
            builder.build(release,out)
            publisher.load_release(out)
            self.assertNotEqual((self.out/'index.html').read_bytes(),(out/'index.html').read_bytes())
        self.assertNotIn(b'<h2>Support guide</h2>',(self.work/'bad/index.html').read_bytes())

    def test_integrity_and_path_rejection(self):
        (self.out/'index.html').write_text('tampered')
        with self.assertRaises(ValueError):
            publisher.load_release(self.out)
        manifest=json.loads((self.out/'manifest.json').read_text())
        manifest['files'][0]['path']='../escape.css'
        (self.out/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            publisher.load_release(self.out)

    def test_upload_order_and_preconditions(self):
        _,plan=publisher.commands(self.out,'lab003-example-docs','123')
        self.assertEqual([p['kind'] for p in plan],['upload','upload','publish-index'])
        self.assertIn('/assets/',plan[0]['command'][4])
        self.assertIn('--if-generation-match=0',plan[0]['command'])
        self.assertIn('--if-generation-match=0',plan[1]['command'])
        self.assertIn('--if-generation-match=123',plan[2]['command'])
        self.assertTrue(plan[2]['command'][4].endswith('/index.html'))
        for bucket in ['production-docs','gs://lab003-example-docs','lab003-a/escape']:
            with self.assertRaises(ValueError):
                publisher.commands(self.out,bucket,'0')

    def test_rollback_verifies_before_publish_and_stops_on_mismatch(self):
        manifest,plan=publisher.commands(self.out,'lab003-example-docs','456',True)
        self.assertEqual([p['kind'] for p in plan],['verify','verify','publish-index'])
        calls=[]
        def mismatch(command,**kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command,0,stdout=b'wrong-content')
        with self.assertRaises(ValueError):
            publisher.execute(plan,mismatch)
        self.assertEqual(len(calls),1)
        calls=[]
        asset=next(f for f in manifest['files'] if f['path']!='index.html')
        payloads=[(self.out/asset['path']).read_bytes(),(self.out/'index.html').read_bytes(),b'']
        def good(command,**kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command,0,stdout=payloads[len(calls)-1])
        publisher.execute(plan,good)
        self.assertEqual(len(calls),3)

    def test_publish_failure_not_bypassed(self):
        _,plan=publisher.commands(self.out,'lab003-example-docs','0')
        calls=[]
        def fail(command,**kwargs):
            calls.append(command)
            raise subprocess.CalledProcessError(1,command)
        with self.assertRaises(subprocess.CalledProcessError):
            publisher.execute(plan,fail)
        self.assertEqual(len(calls),1)

    def test_cli_default_is_dry_run_without_gcloud(self):
        run=subprocess.run([sys.executable,str(ROOT/'scripts/publish-release.py'),
             '--release-dir',str(self.out),'--bucket','lab003-example-docs',
             '--expected-generation','0'],capture_output=True,text=True,timeout=5)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout)['mode'],'dry-run')

if __name__=='__main__':
    unittest.main(verbosity=2)
