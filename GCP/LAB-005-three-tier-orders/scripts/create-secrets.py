"""Create a NEW private Orders secret bundle; never commit or screenshot contents."""
import argparse
import json
import os
from pathlib import Path
import secrets
from werkzeug.security import generate_password_hash

def generate(target):
    root=Path(target)
    root.mkdir(mode=0o700,exist_ok=False,parents=False)
    def write(name,value):
        with os.fdopen(os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as handle:
            json.dump(value,handle,indent=2)
    users={}
    logins={}
    for name,role in [('alice','customer'),('bob','customer'),('operator','operator')]:
        password=secrets.token_urlsafe(24)
        logins[name]=password
        users[name]={'role':role,'password_hash':generate_password_hash(password)}
    write('auth.json',{'session_key':secrets.token_hex(32),'users':users})
    write('demo-logins.json',logins)
    write('db.json',{'database':'orders','user':'orders_app','password':secrets.token_urlsafe(32)})
    admin_password=secrets.token_urlsafe(32)
    write('bootstrap-admin.json',{'database':'orders','user':'postgres','password':admin_password})
    write('sql-admin-flags.json',{'--password':admin_password})
    with os.fdopen(os.open(root/'sql-admin-password.txt',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as handle:
        handle.write(admin_password+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',required=True)
    args=p.parse_args()
    generate(args.out)
    print('Created private bundle. No secret values printed. Keep secrets/ out of Git and screenshots.')
if __name__=='__main__':
    main()
