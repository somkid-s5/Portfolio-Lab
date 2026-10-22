"""Release verification uses a private temporary Git fixture, never the user's checkout."""
import gzip
from io import BytesIO
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_tools',ROOT/'scripts/release.py')
release=importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.repo=self.root/'repo'
        self.repo.mkdir()
        self.lab=self.repo/release.PREFIX
        for path in sorted({p for paths in release.LAYOUT.values() for p in paths}):
            target=self.lab/path
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(('committed '+path+'\n').encode())
        secret=self.lab/'secrets/db.json'
        secret.parent.mkdir()
        secret.write_text('CI-only-DO-NOT-PACK')
        def git(*args):
            return subprocess.run(['git','-C',str(self.repo),*args],capture_output=True,check=True,timeout=10).stdout
        git('init','-q')
        git('add','.')
        git('-c','user.name=CI Fixture','-c','user.email=ci@example.invalid','commit','-qm','fixture')
        self.commit=git('rev-parse','HEAD').decode().strip()

    def tearDown(self):
        self.tmp.cleanup()

    def built(self,name='out',version='v1'):
        target=self.root/name
        manifest=release.build(self.commit,version,target,self.repo)
        return target,manifest

    def test_reproducible_pinned_blobs_not_dirty_worktree_or_tracked_secrets(self):
        first,manifest=self.built()
        (self.lab/'app/main.py').write_text('dirty worktree change; never package this')
        second,again=self.built('again')
        self.assertEqual(manifest,again)
        for tier in release.LAYOUT:
            data=(first/(tier+'.tar.gz')).read_bytes()
            self.assertEqual(data,(second/(tier+'.tar.gz')).read_bytes())
            metadata,files=release.inspect_archive(data,manifest['artifacts'][tier]['sha256'],tier)
            self.assertEqual(set(files),set(release.LAYOUT[tier])|{'release.json'})
            self.assertFalse(any(b'CI-only-DO-NOT-PACK' in value for value in files.values()))
            self.assertEqual(metadata['source_commit'],self.commit)
            if tier=='api':
                self.assertEqual(files['app/main.py'],b'committed app/main.py\n')

    def test_unpack_rejects_existing_directory_and_hash_mismatch_without_writes(self):
        source,manifest=self.built()
        archive=source/'api.tar.gz'
        checksum=manifest['artifacts']['api']['sha256']
        output=self.root/'api-release'
        result=release.unpack(archive,checksum,'api',output)
        self.assertEqual(result['tier'],'api')
        original=(output/'app/main.py').read_bytes()
        with self.assertRaises(FileExistsError):
            release.unpack(archive,checksum,'api',output)
        self.assertEqual((output/'app/main.py').read_bytes(),original)
        rejected=self.root/'bad-hash'
        with self.assertRaises(ValueError):
            release.unpack(archive,'0'*64,'api',rejected)
        self.assertFalse(rejected.exists())

    def test_build_refuses_existing_output_and_invalid_commit_or_version(self):
        target,manifest=self.built()
        old=(target/'manifest.json').read_bytes()
        with self.assertRaises(FileExistsError):
            release.build(self.commit,'v1',target,self.repo)
        self.assertEqual((target/'manifest.json').read_bytes(),old)
        for commit,version in [('main','v1'),(self.commit,'broken')]:
            with self.assertRaises(ValueError):
                release.build(commit,version,self.root/'invalid',self.repo)
        self.assertFalse((self.root/'invalid').exists())

    def test_tier_and_file_manifest_mismatches_are_rejected(self):
        source,manifest=self.built()
        data=(source/'web.tar.gz').read_bytes()
        _,files=release.inspect_archive(data,manifest['artifacts']['web']['sha256'],'web')
        metadata=json.loads(files['release.json'])
        metadata['files'][0]['sha256']='0'*64
        files['release.json']=release.json_bytes(metadata)
        corrupt=release.archive_bytes(files)
        with self.assertRaisesRegex(ValueError,'manifest'):
            release.inspect_archive(corrupt,release.digest(corrupt),'web')
        with self.assertRaises(ValueError):
            release.inspect_archive(data,release.digest(data),'api')

    def test_unknown_paths_links_and_duplicate_members_are_rejected(self):
        # Construct hostile metadata inside a hash-pinned fixture. A hash alone
        # does not make an archive safe to unpack.
        for name,kind in [('../escape',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),
                          ('web/index.html',tarfile.SYMTYPE),('web/index.html',tarfile.LNKTYPE),
                          ('web/index.html',tarfile.FIFOTYPE),('secrets/db.json',tarfile.REGTYPE)]:
            raw=BytesIO()
            with tarfile.open(fileobj=raw,mode='w',format=tarfile.USTAR_FORMAT) as handle:
                member=tarfile.TarInfo(name)
                member.type=kind
                member.linkname='../../escape'
                member.size=1 if kind==tarfile.REGTYPE else 0
                handle.addfile(member,BytesIO(b'x') if member.size else None)
            data=gzip.compress(raw.getvalue(),mtime=0)
            archive=self.root/'hostile.tar.gz'
            archive.write_bytes(data)
            out=self.root/'never-created'
            with self.assertRaises(ValueError):
                release.unpack(archive,release.digest(data),'web',out)
            self.assertFalse(out.exists())
        raw=BytesIO()
        with tarfile.open(fileobj=raw,mode='w') as handle:
            for _ in range(2):
                member=tarfile.TarInfo('web/index.html')
                member.size=1
                handle.addfile(member,BytesIO(b'x'))
        data=gzip.compress(raw.getvalue(),mtime=0)
        with self.assertRaises(ValueError):
            release.inspect_archive(data,release.digest(data),'web')

    def test_archive_expansion_and_member_sizes_are_bounded(self):
        data=gzip.compress(b'x'*4096,mtime=0)
        with patch.object(release,'MAX_EXPANDED',1024):
            with self.assertRaisesRegex(ValueError,'Expanded'):
                release.inspect_archive(data,release.digest(data),'web')
        source,manifest=self.built()
        data=(source/'web.tar.gz').read_bytes()
        with patch.object(release,'MAX_ARCHIVE',len(data)-1):
            with self.assertRaises(ValueError):
                release.inspect_archive(data,release.digest(data),'web')
        with patch.object(release,'MAX_FILE',1):
            with self.assertRaises(ValueError):
                release.inspect_archive(data,release.digest(data),'web')

    @unittest.skipUnless(os.name=='posix','Symlink filesystem fixture needs POSIX')
    def test_symlink_output_is_never_followed(self):
        source,manifest=self.built()
        other=self.root/'other'
        other.mkdir()
        (other/'keep').write_text('keep')
        target=self.root/'linked'
        target.symlink_to(other,target_is_directory=True)
        with self.assertRaises(ValueError):
            release.unpack(source/'web.tar.gz',manifest['artifacts']['web']['sha256'],'web',target)
        self.assertEqual((other/'keep').read_text(),'keep')

if __name__=='__main__':
    unittest.main(verbosity=2)
