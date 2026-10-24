"""Create a new private synthetic-login bundle. Refuse existing output."""
import argparse
import json
import os
from pathlib import Path
import secrets
from werkzeug.security import generate_password_hash


def generate(destination):
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    os.chmod(destination, 0o700)
    logins = {name: {"password": secrets.token_urlsafe(24), "role": role}
              for name, role in (("alice", "customer"), ("bob", "customer"),
                                  ("operator", "operator"))}
    auth = {"session_key": secrets.token_hex(32),
            "users": {name: {"password_hash": generate_password_hash(data["password"]),
                              "role": data["role"]}
                      for name, data in logins.items()}}
    for name, value in (("auth.json", auth), ("demo-logins.json", logins)):
        fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        generate(args.out)
        print(json.dumps({"event": "private_login_bundle_created"}))
        return 0
    except Exception as exc:
        print(json.dumps({"event": "bundle_creation_failed",
                          "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
