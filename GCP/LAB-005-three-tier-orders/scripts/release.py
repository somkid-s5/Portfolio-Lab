"""Pinned-commit release bundles; bounded verification before writing any extracted file."""
import argparse
import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path,PurePosixPath
import re
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
PREFIX='GCP/LAB-005-three-tier-orders'
LAYOUT={
 'web':('web/index.html','web/app.js','web/style.css','web/nginx.conf.template','scripts/render-web-config.py'),
 'api':('app/main.py','app/orders.py','app/database.py','requirements.txt','db/schema.sql','db/seed.sql','db/grants.sql','db/check-invariants.sql','scripts/init-db.py','scripts/inspect-db.py')
}
MAX_ARCHIVE=10*1024*1024
MAX_EXPANDED=32*1024*1024
MAX_FILE=4*1024*1024

def digest(data):
    return hashlib.sha256(data).hexdigest()

def json_bytes(value):
    return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()

def validate_identity(tier,commit,version):
    if not isinstance(tier,str) or tier not in LAYOUT or not isinstance(commit,str) or not re.fullmatch('[0-9a-f]{40}',commit) or version not in ('v1','v2'):
        raise ValueError('Expected an allowed tier, full lowercase commit SHA and v1/v2')

def archive_bytes(files):
    """Deterministic regular-file USTAR/gzip; no extraction or filesystem scan."""
    tar=BytesIO()
    with tarfile.open(fileobj=tar,mode='w',format=tarfile.USTAR_FORMAT) as handle:
        for name,data in sorted(files.items()):
            member=tarfile.TarInfo(name)
            member.size=len(data)
            member.mode=0o644
            member.mtime=0
            member.uid=member.gid=0
            member.uname=member.gname=''
            handle.addfile(member,BytesIO(data))
    output=BytesIO()
    with gzip.GzipFile(fileobj=output,filename='',mode='wb',mtime=0,compresslevel=9) as handle:
        handle.write(tar.getvalue())
    data=output.getvalue()
    if len(data)>MAX_ARCHIVE or len(tar.getvalue())>MAX_EXPANDED:
        raise ValueError('Release exceeds bounded archive size')
    return data

def build(commit,version,out,repo=None):
    repo=Path(repo or ROOT.parents[1]).resolve()
    validate_identity('api',commit,version)
    actual=subprocess.run(['git','-C',str(repo),'rev-parse','--verify',commit+'^{commit}'],
                          capture_output=True,check=True,timeout=10).stdout.decode().strip()
    if actual!=commit:
        raise ValueError('Source commit is not the exact requested commit')
    artifacts={}
    manifest={'schema':1,'lab':'LAB-005','source_commit':commit,'app_version':version,'artifacts':{}}
    for tier,paths in LAYOUT.items():
        files={}
        for path in paths:
            # Read committed blobs, not a dirty worktree, private files or generated evidence.
            blob_ref=commit+':'+PREFIX+'/'+path
            size=subprocess.run(['git','-C',str(repo),'cat-file','-s',blob_ref],
                                capture_output=True,check=True,timeout=10).stdout
            if int(size)>MAX_FILE:
                raise ValueError('Committed file exceeds size bound')
            result=subprocess.run(['git','-C',str(repo),'show',blob_ref],
                                  capture_output=True,check=True,timeout=10)
            if len(result.stdout)>MAX_FILE:
                raise ValueError('Committed file exceeds size bound')
            files[path]=result.stdout
        metadata={'schema':1,'lab':'LAB-005','tier':tier,'source_commit':commit,'app_version':version,
                  'files':[{'path':p,'sha256':digest(data),'size':len(data)} for p,data in sorted(files.items())]}
        files['release.json']=json_bytes(metadata)
        data=archive_bytes(files)
        checksum=digest(data)
        artifacts[tier]=data
        manifest['artifacts'][tier]={'filename':tier+'.tar.gz','sha256':checksum,'size':len(data),
                                    'object_name':'releases/'+checksum+'/'+tier+'.tar.gz'}
    target=Path(out)
    if target.is_symlink():
        raise ValueError('Refusing symlink output')
    target.mkdir(mode=0o755,exist_ok=False,parents=False)
    for tier,data in artifacts.items():
        with (target/(tier+'.tar.gz')).open('xb') as handle:
            handle.write(data)
    with (target/'manifest.json').open('xb') as handle:
        handle.write(json_bytes(manifest))
    return manifest

def inspect_archive(data,expected_sha,tier):
    if not isinstance(tier,str) or tier not in LAYOUT or not isinstance(expected_sha,str) or not re.fullmatch('[0-9a-f]{64}',expected_sha):
        raise ValueError('Expected a pinned SHA256 and allowed tier')
    if len(data)>MAX_ARCHIVE or digest(data)!=expected_sha:
        raise ValueError('Archive size or SHA256 mismatch')
    with gzip.GzipFile(fileobj=BytesIO(data),mode='rb') as compressed:
        expanded=compressed.read(MAX_EXPANDED+1)
    if len(expanded)>MAX_EXPANDED:
        raise ValueError('Expanded archive exceeds bound')
    allowed=set(LAYOUT[tier])|{'release.json'}
    files={}
    with tarfile.open(fileobj=BytesIO(expanded),mode='r:') as handle:
        for member in handle:
            name=member.name
            path=PurePosixPath(name)
            if (not member.isfile() or member.issparse() or member.pax_headers or
                name not in allowed or path.is_absolute() or '..' in path.parts or
                path.as_posix()!=name or '\\' in name or name in files or
                not 0<=member.size<=MAX_FILE):
                raise ValueError('Unexpected, duplicate, linked or unsafe archive member')
            if len(files)>=len(allowed):
                raise ValueError('Too many archive members')
            stream=handle.extractfile(member)
            if stream is None:
                raise ValueError('Missing member content')
            with stream:
                payload=stream.read(MAX_FILE+1)
            if len(payload)!=member.size:
                raise ValueError('Invalid member length')
            files[name]=payload
    if set(files)!=allowed:
        raise ValueError('Release layout incomplete')
    metadata=json.loads(files['release.json'])
    if not isinstance(metadata,dict) or set(metadata)!={'schema','lab','tier','source_commit','app_version','files'} or type(metadata['schema']) is not int or metadata['schema']!=1 or metadata['lab']!='LAB-005' or metadata['tier']!=tier:
        raise ValueError('Invalid release metadata')
    validate_identity(tier,metadata['source_commit'],metadata['app_version'])
    entries=metadata['files']
    if not isinstance(entries,list) or len(entries)!=len(LAYOUT[tier]):
        raise ValueError('Invalid file manifest')
    for entry in entries:
        if (not isinstance(entry,dict) or set(entry)!={'path','size','sha256'} or
            not isinstance(entry['path'],str) or type(entry['size']) is not int or
            not isinstance(entry['sha256'],str)):
            raise ValueError('Invalid file record')
    expected=[{'path':p,'sha256':digest(files[p]),'size':len(files[p])} for p in sorted(LAYOUT[tier])]
    if metadata['files']!=expected:
        raise ValueError('File manifest mismatch')
    return metadata,files

def unpack(archive,expected_sha,tier,out):
    with Path(archive).open('rb') as handle:
        data=handle.read(MAX_ARCHIVE+1)
    metadata,files=inspect_archive(data,expected_sha,tier)
    target=Path(out)
    if target.is_symlink():
        raise ValueError('Refusing symlink destination')
    # All archive members and digests are verified before creating the destination.
    # Existing releases are immutable. An I/O failure may leave an inactive partial
    # directory; callers must never activate it or blindly overwrite it on retry.
    target.mkdir(mode=0o755,exist_ok=False,parents=False)
    for name,payload in sorted(files.items()):
        path=target/name
        path.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
        with path.open('xb') as handle:
            handle.write(payload)
        os.chmod(path,0o644)
    return metadata

def main():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest='command',required=True)
    build_parser=commands.add_parser('build')
    build_parser.add_argument('--source-commit',required=True)
    build_parser.add_argument('--app-version',choices=['v1','v2'],default='v1')
    build_parser.add_argument('--out',required=True)
    extract=commands.add_parser('unpack')
    extract.add_argument('--archive',required=True)
    extract.add_argument('--sha256',required=True)
    extract.add_argument('--tier',choices=sorted(LAYOUT),required=True)
    extract.add_argument('--out',required=True)
    args=p.parse_args()
    if args.command=='build':
        result=build(args.source_commit,args.app_version,args.out)
    else:
        result=unpack(args.archive,args.sha256,args.tier,args.out)
    print(json.dumps(result,sort_keys=True))
if __name__=='__main__':
    main()
