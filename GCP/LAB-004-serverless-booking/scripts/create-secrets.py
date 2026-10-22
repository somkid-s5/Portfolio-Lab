"""Create a NEW sandbox secret bundle. Never commit or screenshot its contents."""
import argparse
import json
import os
from pathlib import Path
import secrets
from werkzeug.security import generate_password_hash

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    root=Path(args.out)
    root.mkdir(mode=0o700,parents=False,exist_ok=False)
    def write(name,data):
        with (root/name).open('x') as handle:
            os.chmod(handle.name,0o600)
            json.dump(data,handle,indent=2)
    users={}
    logins={}
    for username,role in [('alice','booker'),('bob','booker'),('operator','operator')]:
        password=secrets.token_urlsafe(24)
        logins[username]=password
        users[username]={'role':role,'password_hash':generate_password_hash(password)}
    write('auth.json',{'session_key':secrets.token_hex(32),'users':users})
    write('demo-logins.json',logins)
    for suffix in ['a','b']:
        write('db-'+suffix+'.json',{'database':'booking','user':'booking_'+suffix,
                                   'password':secrets.token_urlsafe(32)})
    with (root/'sql-admin-password.txt').open('x') as handle:
        os.chmod(handle.name,0o600)
        admin_password=secrets.token_urlsafe(32)
        handle.write(admin_password+'\n')
    write('bootstrap-admin.json',{'database':'booking','user':'postgres',
                                 'password':admin_password})
    print('Created new private bundle. No secret values printed. Do not commit secrets/.')

if __name__=='__main__':
    main()
