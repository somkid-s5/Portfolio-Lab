"""Dry-run by default. --apply uploads only to the explicitly named lab bucket."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HTML_CACHE='public,max-age=60'
ASSET_CACHE='public,max-age=31536000,immutable'

def load_release(directory):
    root=Path(directory).resolve()
    manifest=json.loads((root/'manifest.json').read_text())
    if manifest.get('schema')!=1 or manifest.get('release') not in ('v1','v2','bad'):
        raise ValueError('Invalid manifest release/schema')
    release=manifest['release']
    files=manifest.get('files',[])
    if len(files)!=2 or {f.get('path') for f in files}=={'index.html'}:
        raise ValueError('Expected exactly index and one asset')
    seen=set()
    for entry in files:
        name=entry['path']
        if name in seen or (name!='index.html' and not re.fullmatch(
            'releases/'+release+r'/assets/docs\.[a-f0-9]{16}\.css',name)):
            raise ValueError('Invalid or duplicate object path')
        seen.add(name)
        local=root/name
        if local.is_symlink() or root not in local.resolve().parents:
            raise ValueError('Symlink or outside release directory')
        raw=local.read_bytes()
        cache_ok=(entry['cache_control'] in ('public,max-age=15','public,max-age=60','public,max-age=600')
                  if name=='index.html' else entry['cache_control']==ASSET_CACHE)
        expected_type='text/html; charset=utf-8' if name=='index.html' else 'text/css'
        if (entry['size']!=len(raw) or entry['sha256']!=hashlib.sha256(raw).hexdigest()
            or not cache_ok or entry['content_type']!=expected_type):
            raise ValueError('Manifest integrity or metadata mismatch')
    if 'index.html' not in seen:
        raise ValueError('Missing index')
    asset=next(e for e in files if e['path']!='index.html')
    if asset['sha256'][:16] not in asset['path']:
        raise ValueError('Asset filename hash mismatch')
    if ('href="/'+asset['path']+'"').encode() not in (root/'index.html').read_bytes():
        raise ValueError('Index asset reference mismatch')
    return root,manifest

def commands(directory,bucket,expected_generation,index_only=False,reuse_assets=False):
    if index_only and reuse_assets:
        raise ValueError('Choose index-only or reuse-assets, not both')
    if not re.fullmatch(r'lab003-[a-z0-9][a-z0-9-]{3,50}[a-z0-9]',bucket):
        raise ValueError('Bucket must be an explicitly named lab003- sandbox bucket')
    if not re.fullmatch(r'0|[1-9][0-9]*',str(expected_generation)):
        raise ValueError('Expected generation must be a nonnegative integer')
    root,manifest=load_release(directory)
    index=next(e for e in manifest['files'] if e['path']=='index.html')
    asset=next(e for e in manifest['files'] if e['path']!='index.html')
    archive=f"releases/{manifest['release']}/index.html"
    plan=[]
    if index_only:
        for entry,name in [(asset,asset['path']),(index,archive)]:
            plan.append({'kind':'verify','command':['gcloud','storage','cat',f'gs://{bucket}/{name}'],
                         'sha256':entry['sha256']})
    else:
        uploads=[(asset,asset['path']),(index,archive)]
        if reuse_assets:
            plan.append({'kind':'verify','command':['gcloud','storage','cat',f"gs://{bucket}/{asset['path']}"],
                         'sha256':asset['sha256']})
            uploads=[(index,archive)]
        for entry,name in uploads:
            plan.append({'kind':'upload','command':['gcloud','storage','cp',
                str(root/entry['path']),f'gs://{bucket}/{name}','--if-generation-match=0',
                '--content-type='+entry['content_type'],'--cache-control='+entry['cache_control']]})
    plan.append({'kind':'publish-index','command':['gcloud','storage','cp',
        str(root/'index.html'),f'gs://{bucket}/index.html',
        '--if-generation-match='+str(expected_generation),'--content-type='+index['content_type'],
        '--cache-control='+index['cache_control']]})
    return manifest,plan

def execute(plan,runner=subprocess.run):
    for step in plan:
        result=runner(step['command'],check=True,capture_output=True)
        if step['kind']=='verify' and hashlib.sha256(result.stdout).hexdigest()!=step['sha256']:
            raise ValueError('Remote archived release differs; index not published')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-dir',required=True)
    parser.add_argument('--bucket',required=True)
    parser.add_argument('--expected-generation',required=True)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--index-only',action='store_true',help='Rollback/promote previously uploaded verified release')
    modes.add_argument('--reuse-assets',action='store_true',help='Resume after assets exist but archive index is absent')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    manifest,plan=commands(args.release_dir,args.bucket,args.expected_generation,args.index_only,args.reuse_assets)
    print(json.dumps({'release':manifest['release'],'mode':'apply' if args.apply else 'dry-run',
                      'steps':plan},indent=2))
    if args.apply:
        execute(plan)
        print('Index uploaded using generation precondition. CDN/browser convergence must be checked separately.')

if __name__=='__main__':
    main()
