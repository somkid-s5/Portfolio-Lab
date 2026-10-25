"""Fixed synthetic accounts and an explicitly bounded password-hash policy."""
from pathlib import Path
import re
from order_domain import read_json

USER_ROLES={"alice":"customer","bob":"customer","operator":"operator"}
HASH_METHOD="scrypt:32768:8:1"
HASH_PATTERN=r"scrypt:32768:8:1\$[A-Za-z0-9]{16}\$[a-f0-9]{128}"


def validate_auth(value):
    if (not isinstance(value,dict) or set(value)!={"session_key","users"} or
            not isinstance(value["session_key"],str) or
            not re.fullmatch(r"[a-f0-9]{64}",value["session_key"]) or
            not isinstance(value["users"],dict) or set(value["users"])!=set(USER_ROLES)):
        raise ValueError("invalid_auth_bundle")
    users={}
    for name,role in USER_ROLES.items():
        entry=value["users"][name]
        if (not isinstance(entry,dict) or set(entry)!={"role","password_hash"} or
                entry["role"]!=role or not isinstance(entry["password_hash"],str) or
                not re.fullmatch(HASH_PATTERN,entry["password_hash"])):
            raise ValueError("invalid_auth_bundle")
        users[name]={"role":role,"password_hash":entry["password_hash"]}
    return {"session_key":value["session_key"],"users":users}


def read_auth(path):
    with Path(path).open("rb") as handle:
        value=read_json(handle.read(4097))
    return validate_auth(value)
