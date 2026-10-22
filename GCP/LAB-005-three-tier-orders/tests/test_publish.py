import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import release
spec=importlib.util.spec_from_file_location('publish_release',ROOT/'scripts/publish-release.py')
publisher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)

class PublishTests(unittest.TestCase):
    def fixture(self,root):
        manifest={'schema':1,'lab':'LAB-005','source_commit':'a'*40,'app_version':'v1','artifacts':{}}
        for tier,paths in release.LAYOUT.items():
            files={path:b'test fixture\n' for path in paths}
            metadata={'schema':1,'lab':'LAB-005','tier':tier,'source_commit':'a'*40,'app_version':'v1',
                      'files':[{'path':p,'size':len(v),'sha256':release.digest(v)} for p,v in sorted(files.items())]}
            files['release.json']=release.json_bytes(metadata)
            data=release.archive_bytes(files)
            checksum=release.digest(data)
            (root/(tier+'.tar.gz')).write_bytes(data)
            manifest['artifacts'][tier]={'filename':tier+'.tar.gz','size':len(data),'sha256':checksum,
                                         'object_name':'releases/'+checksum+'/'+tier+'.tar.gz'}
        (root/'manifest.json').write_bytes(release.json_bytes(manifest))
        return manifest

    def test_create_only_plan_validates_both_tiers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root)
            result=publisher.plan(root,'private-lab-bucket')
            self.assertEqual(result['mode'],'dry-run-only')
            self.assertEqual(len(result['commands']),2)
            for command in result['commands']:
                self.assertIn('--if-generation-match=0',command)
                self.assertIn('--cache-control=no-store',command)
                self.assertFalse(any('public' in part for part in command))
            self.assertEqual(set(result['sha256']),{'web','api'})

    def test_tampered_archive_and_manifest_paths_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            manifest=self.fixture(root)
            (root/'api.tar.gz').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                publisher.plan(root,'private-lab-bucket')
            self.fixture(root)
            manifest['artifacts']['web']['filename']='../private.json'
            (root/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                publisher.plan(root,'private-lab-bucket')

    def test_bucket_and_link_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root)
            for bucket in ['gs://bucket','bucket/path','bucket;echo bad']:
                with self.assertRaises(ValueError):
                    publisher.plan(root,bucket)
            link=root/'link'
            link.symlink_to(root,target_is_directory=True)
            with self.assertRaises(ValueError):
                publisher.plan(link,'private-lab-bucket')
