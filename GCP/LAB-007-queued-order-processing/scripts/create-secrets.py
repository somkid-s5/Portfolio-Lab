"""Create NEW private auth/DB bundles. No cloud calls and no secrets on stdout."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from auth_config import HASH_METHOD,USER_ROLES,validate_auth
from database import USERS
from werkzeug.security import generate_password_hash


def generate(destination):
    target=Path(destination)
    target.mkdir(mode=0o700)
    os.chmod(target,0o700)
    logins={name:{"password":secrets.token_urlsafe(24),"role":role}
            for name,role in USER_ROLES.items()}
    auth=validate_auth({"session_key":secrets.token_hex(32),"users":{
        name:{"password_hash":generate_password_hash(value["password"],
              method=HASH_METHOD,salt_length=16),"role":value["role"]}
        for name,value in logins.items()}})
    values={"auth.json":auth,"demo-logins.json":logins}
    for role,user in {**USERS,"bootstrap":"postgres"}.items():
        values["db-"+role+".json"]={"user":user,"password":secrets.token_urlsafe(32),
                                   "database":"order_queue"}
    for name,value in values.items():
        fd=os.open(target/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as handle:
            json.dump(value,handle,sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    try:
        generate(args.out)
        print(json.dumps({"event":"private_bundle_created"}))
        return 0
    except Exception as exc:
        print(json.dumps({"event":"bundle_creation_failed","error_type":type(exc).__name__}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
