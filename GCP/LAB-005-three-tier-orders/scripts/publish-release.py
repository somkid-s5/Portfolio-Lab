"""Validate local release and print create-only upload commands. Never calls GCP."""
import argparse
import json
from pathlib import Path
import re
import shlex
from release import MAX_ARCHIVE,inspect_archive,validate_identity

def plan(directory,bucket):
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]',bucket):
        raise ValueError('Expected bare artifact bucket name')
    root=Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Expected release directory, not symlink')
    root=root.resolve()
    manifest_path=root/'manifest.json'
    if manifest_path.is_symlink() or manifest_path.stat().st_size>65536:
        raise ValueError('Invalid manifest file')
    manifest=json.loads(manifest_path.read_bytes())
    if (not isinstance(manifest,dict) or set(manifest)!={'schema','lab','source_commit','app_version','artifacts'} or
        type(manifest['schema']) is not int or manifest['schema']!=1 or manifest['lab']!='LAB-005' or
        not isinstance(manifest['artifacts'],dict) or set(manifest['artifacts'])!={'web','api'}):
        raise ValueError('Unexpected release manifest')
    validate_identity('api',manifest['source_commit'],manifest['app_version'])
    commands=[]
    hashes={}
    for tier in ('web','api'):
        item=manifest['artifacts'][tier]
        if not isinstance(item,dict) or set(item)!={'filename','sha256','size','object_name'}:
            raise ValueError('Unexpected artifact record')
        checksum=item['sha256']
        if not isinstance(checksum,str) or not re.fullmatch('[a-f0-9]{64}',checksum):
            raise ValueError('Invalid artifact hash')
        expected='releases/'+checksum+'/'+tier+'.tar.gz'
        if item['filename']!=tier+'.tar.gz' or item['object_name']!=expected or type(item['size']) is not int:
            raise ValueError('Unexpected artifact path or size')
        path=root/item['filename']
        if path.is_symlink() or path.stat().st_size!=item['size'] or not 0<item['size']<=MAX_ARCHIVE:
            raise ValueError('Artifact file size or type invalid')
        with path.open('rb') as handle:
            data=handle.read(MAX_ARCHIVE+1)
        metadata,_=inspect_archive(data,checksum,tier)
        if metadata['source_commit']!=manifest['source_commit'] or metadata['app_version']!=manifest['app_version']:
            raise ValueError('Release identity differs between tiers')
        hashes[tier]=checksum
        commands.append(['gcloud','storage','cp',str(path),'gs://'+bucket+'/'+expected,
                         '--if-generation-match=0','--content-type=application/gzip',
                         '--cache-control=no-store'])
    return {'mode':'dry-run-only','source_commit':manifest['source_commit'],
            'app_version':manifest['app_version'],'sha256':hashes,'commands':commands,
            'existing_object':'Stop on precondition failure. Download and verify the existing object before reuse; never remove the generation guard.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-dir',required=True)
    parser.add_argument('--bucket',required=True)
    parser.add_argument('--shell',action='store_true',help='Print quoted Bash commands for separate manual review/execution')
    args=parser.parse_args()
    result=plan(args.release_dir,args.bucket)
    if args.shell:
        print('# Reviewed local files only; commands below have NOT been executed.')
        print('set -eu')
        for command in result['commands']:
            print(shlex.join(command))
    else:
        print(json.dumps(result,indent=2,sort_keys=True))
if __name__=='__main__':
    main()
