"""Write private app configuration on an App VM. Does not start the service."""
import argparse
import os
from pathlib import Path
import re

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--password-file',required=True)
    parser.add_argument('--hash-file',required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:
        parser.error('Run with sudo on target App VM')
    password=Path(args.password_file).read_text().strip()
    if not re.fullmatch('[A-Za-z0-9_-]{32,100}',password):
        parser.error('Expected generated URL-safe password')
    root=Path('/etc/lab002')
    root.mkdir(mode=0o755,exist_ok=True)
    # Root owns config; systemd reads EnvironmentFile before changing User.
    os.umask(0o077)
    config=root/'app.env'
    config.write_text('PGHOST=10.22.20.10\nPGPORT=5432\nPGDATABASE=inventory\n'
                      'PGUSER=inventory_app\nPGPASSWORD='+password+'\nPORT=8080\n')
    config.chmod(0o600)
    hashes=root/'token-hashes.json'
    hashes.write_bytes(Path(args.hash_file).read_bytes())
    hashes.chmod(0o600)
    print('Private App config written. Run install-app.sh next; no secret values printed.')

if __name__=='__main__':
    main()
