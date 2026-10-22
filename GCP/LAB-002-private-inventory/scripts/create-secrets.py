"""Create a NEW local secret bundle for a sandbox. Never commit the output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,help='New directory only')
    args=parser.parse_args()
    root=Path(args.out)
    root.mkdir(mode=0o700,parents=False,exist_ok=False)
    hashes={}
    for role in ['reader','operator']:
        token=secrets.token_urlsafe(32)
        path=root/(role+'.token')
        with path.open('x') as handle:
            os.chmod(path,0o600)
            handle.write(token+'\n')
        hashes[role]=hashlib.sha256(token.encode()).hexdigest()
    with (root/'token-hashes.json').open('x') as handle:
        os.chmod(handle.name,0o600)
        json.dump(hashes,handle)
    with (root/'db-password.txt').open('x') as handle:
        os.chmod(handle.name,0o600)
        handle.write(secrets.token_urlsafe(32)+'\n')
    print('Secret bundle created. Filenames only; do not commit or screenshot contents.')
    print(root)

if __name__=='__main__':
    main()
