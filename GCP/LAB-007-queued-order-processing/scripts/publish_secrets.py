"""Publish Lab 07 secret files and initialize a fresh Cloud SQL postgres password.

This script is for an authenticated Cloud Shell session. Secret bytes stay in
memory and travel over HTTPS; they never appear in argv or stdout.
"""
import argparse
import base64
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


REGION = "asia-southeast1"
INSTANCE = "lab007-orders"
DATABASE = "order_queue"
NETWORK = "lab007-vpc"
SECRET_FILES = {
    "lab007-auth": "auth.json",
    "lab007-db-portal": "db-portal.json",
    "lab007-db-worker": "db-worker.json",
    "lab007-db-dispatcher": "db-dispatcher.json",
    "lab007-db-bootstrap": "db-bootstrap.json",
}
DB_USERS = {
    "db-portal.json": "order_api",
    "db-worker.json": "order_worker",
    "db-dispatcher.json": "outbox_dispatcher",
    "db-bootstrap.json": "postgres",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
DEMO_PASSWORD_RE = re.compile(r"[A-Za-z0-9_-]{32}\Z")
AUTH_HASH_RE = re.compile(r"scrypt:32768:8:1\$[A-Za-z0-9]{16}\$[a-f0-9]{128}\Z")
HEX_KEY_RE = re.compile(r"[a-f0-9]{64}\Z")
STATE_NAME = ".lab007-publish-state.json"
LOCK_NAME = ".lab007-publish.lock"


class SafeFailure(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("invalid_json_constant")


def _read_private_file(path, limit=16384):
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise SafeFailure("private_file_permissions_invalid")
        raw = os.read(fd, limit + 1)
        if len(raw) > limit:
            raise SafeFailure("private_file_too_large")
        return raw
    finally:
        os.close(fd)


def _load_json(raw):
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_pairs_no_duplicates,
        parse_constant=_reject_constant,
    )


def validate_bundle(directory):
    directory = Path(directory)
    try:
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
            raise SafeFailure("private_directory_permissions_invalid")
        expected = set(SECRET_FILES.values()) | {"demo-logins.json"}
        found = {entry.name for entry in directory.iterdir()}
    except SafeFailure:
        raise
    except OSError:
        raise SafeFailure("private_bundle_unavailable") from None
    allowed_state = {STATE_NAME, LOCK_NAME}
    if found - allowed_state != expected or found - (expected | allowed_state):
        raise SafeFailure("private_bundle_file_set_invalid")

    raw_values = {}
    parsed = {}
    try:
        for filename in expected:
            raw = _read_private_file(directory / filename, 8192)
            raw_values[filename] = raw
            parsed[filename] = _load_json(raw)
    except SafeFailure:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        raise SafeFailure("private_bundle_invalid") from None

    auth = parsed["auth.json"]
    if (not isinstance(auth, dict) or set(auth) != {"session_key", "users"} or
            not isinstance(auth["session_key"], str) or
            not HEX_KEY_RE.fullmatch(auth["session_key"]) or
            not isinstance(auth["users"], dict) or
            set(auth["users"]) != {"alice", "bob", "operator"}):
        raise SafeFailure("auth_bundle_invalid")
    roles = {"alice": "customer", "bob": "customer", "operator": "operator"}
    for name, role in roles.items():
        entry = auth["users"][name]
        if (not isinstance(entry, dict) or set(entry) != {"role", "password_hash"} or
                entry["role"] != role or not isinstance(entry["password_hash"], str) or
                not AUTH_HASH_RE.fullmatch(entry["password_hash"])):
            raise SafeFailure("auth_bundle_invalid")

    demo = parsed["demo-logins.json"]
    if (not isinstance(demo, dict) or set(demo) != set(roles) or
            any(not isinstance(demo[name], dict) or
                set(demo[name]) != {"password", "role"} or
                demo[name]["role"] != roles[name] or
                not isinstance(demo[name]["password"], str) or
                not DEMO_PASSWORD_RE.fullmatch(demo[name]["password"])
                for name in roles)):
        raise SafeFailure("demo_login_bundle_invalid")

    for filename, username in DB_USERS.items():
        value = parsed[filename]
        if (not isinstance(value, dict) or set(value) != {"user", "password", "database"} or
                value["user"] != username or value["database"] != DATABASE or
                not isinstance(value["password"], str) or
                not TOKEN_RE.fullmatch(value["password"])):
            raise SafeFailure("database_bundle_invalid")
    return raw_values, parsed


def _json_bytes(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _read_state(directory):
    path = Path(directory) / STATE_NAME
    try:
        raw = _read_private_file(path, 2048)
    except FileNotFoundError:
        if (Path(directory) / (STATE_NAME + ".tmp")).exists():
            raise SafeFailure("private_state_recovery_required") from None
        return None
    except SafeFailure:
        raise
    except OSError:
        raise SafeFailure("private_state_unavailable") from None
    try:
        state = _load_json(raw)
    except (UnicodeError, ValueError, TypeError):
        raise SafeFailure("private_state_invalid") from None
    required = {"version", "project", "instance", "bootstrap_password_sha256", "password_state"}
    if (not isinstance(state, dict) or set(state) != required or state["version"] != 1 or
            state["instance"] != INSTANCE or
            state["password_state"] not in {"pending", "set"} or
            not isinstance(state["project"], str) or
            not isinstance(state["bootstrap_password_sha256"], str) or
            not HEX_KEY_RE.fullmatch(state["bootstrap_password_sha256"])):
        raise SafeFailure("private_state_invalid")
    return state


def _write_state(directory, state):
    directory = Path(directory)
    target = directory / STATE_NAME
    temporary = directory / (STATE_NAME + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(temporary, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(_json_bytes(state) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except SafeFailure:
        raise
    except OSError:
        raise SafeFailure("private_state_write_failed") from None


def _api_path(project, resource):
    return quote(project, safe="-") + "/" + resource


class GoogleAPI:
    def __init__(self, token):
        self.token = token

    def request(self, method, url, body=None, not_found_ok=False):
        headers = {"Authorization": "Bearer " + self.token}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            data = _json_bytes(body)
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=15) as response:
                payload = response.read(1024 * 1024 + 1)
                if len(payload) > 1024 * 1024:
                    raise SafeFailure("google_api_response_too_large")
                return json.loads(payload.decode("utf-8")) if payload else {}
        except HTTPError as error:
            if error.code == 404 and not_found_ok:
                return None
            if error.code in {401, 403}:
                raise SafeFailure("permission_or_api_disabled") from None
            if error.code == 404:
                raise SafeFailure("required_cloud_resource_not_found") from None
            raise SafeFailure("google_api_request_failed") from None
        except SafeFailure:
            raise
        except (URLError, TimeoutError, OSError, UnicodeError, ValueError):
            raise SafeFailure("google_api_request_failed") from None


def _secret_resource(project, secret_id):
    return (f"https://secretmanager.googleapis.com/v1/projects/{quote(project, safe='-')}"
            f"/locations/{REGION}/secrets/{secret_id}")


def _sql_resource(project, suffix):
    return f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{quote(project, safe='-')}/{suffix}"


def _preflight(api, project, raw_values):
    instance = api.request(
        "GET", _sql_resource(project, "instances/" + INSTANCE)
    )
    settings = instance.get("settings", {})
    ip = settings.get("ipConfiguration", {})
    network = ip.get("privateNetwork", "")
    if (instance.get("name") != INSTANCE or
            instance.get("region") != REGION or
            instance.get("databaseVersion") != "POSTGRES_16" or
            instance.get("state") != "RUNNABLE" or
            ip.get("ipv4Enabled") is not False or
            not network.endswith("/networks/" + NETWORK)):
        raise SafeFailure("cloud_sql_instance_does_not_match_lab")

    users_url = _sql_resource(project, "instances/" + INSTANCE + "/users")
    users = api.request("GET", users_url + "?" + urlencode({"name": "postgres"}))
    if not any(user.get("name") == "postgres" for user in users.get("items", [])):
        raise SafeFailure("postgres_user_not_found")

    plans = {}
    for secret_id, filename in SECRET_FILES.items():
        resource = _secret_resource(project, secret_id)
        secret = api.request("GET", resource)
        managed = secret.get("replication", {}).get("userManaged", {})
        replicas = managed.get("replicas", [])
        if [item.get("location") for item in replicas] != [REGION]:
            raise SafeFailure("secret_location_does_not_match_lab")
        current = api.request(
            "GET", resource + "/versions/latest:access", not_found_ok=True
        )
        if current is None:
            plans[secret_id] = {"filename": filename, "version": None}
            continue
        try:
            current_bytes = base64.b64decode(
                current["payload"]["data"], validate=True
            )
        except (KeyError, ValueError, TypeError):
            raise SafeFailure("secret_version_unreadable") from None
        if not hmac.compare_digest(
            hashlib.sha256(current_bytes).digest(),
            hashlib.sha256(raw_values[filename]).digest(),
        ):
            raise SafeFailure("existing_secret_version_differs_refuse_rotation")
        version = current.get("name")
        if not isinstance(version, str) or not re.search(r"/versions/[1-9][0-9]*\Z", version):
            raise SafeFailure("secret_version_name_invalid")
        plans[secret_id] = {"filename": filename, "version": version}
    return plans


def _publish_version(api, project, secret_id, raw):
    resource = _secret_resource(project, secret_id)
    payload = {"payload": {"data": base64.b64encode(raw).decode("ascii")}}
    result = api.request("POST", resource + ":addVersion", body=payload)
    name = result.get("name")
    if not isinstance(name, str) or not re.search(r"/versions/[1-9][0-9]*\Z", name):
        raise SafeFailure("secret_version_outcome_unknown")
    return name.rsplit("/", 1)[-1]

def _password_state(api, project, directory, password, state, initialize):
    fingerprint = hashlib.sha256(password.encode("ascii")).hexdigest()
    if state is None:
        if not initialize:
            raise SafeFailure("first_run_requires_initialize_flag")
        state = {
            "version": 1,
            "project": project,
            "instance": INSTANCE,
            "bootstrap_password_sha256": fingerprint,
            "password_state": "pending",
        }
        _write_state(directory, state)
    elif (state["project"] != project or
          not hmac.compare_digest(state["bootstrap_password_sha256"], fingerprint)):
        raise SafeFailure("private_state_bundle_or_project_mismatch")

    if state["password_state"] == "set":
        return "preserved"

    body = {"name": "postgres", "password": password}
    url = _sql_resource(
        project,
        "instances/" + INSTANCE + "/users?" + urlencode({"name": "postgres"}),
    )
    operation = api.request("PUT", url, body=body)
    operation_name = operation.get("name")
    if not isinstance(operation_name, str) or not operation_name:
        raise SafeFailure("password_update_outcome_unknown")
    operation_id = operation_name.rsplit("/", 1)[-1]
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = api.request(
            "GET", _sql_resource(project, "operations/" + quote(operation_id, safe="-"))
        )
        if result.get("status") == "DONE":
            if result.get("error"):
                raise SafeFailure("password_update_failed")
            state["password_state"] = "set"
            _write_state(directory, state)
            return "initialized"
        time.sleep(2)
    raise SafeFailure("password_update_outcome_unknown")




def publish(project, directory, initialize=False, api=None):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
        raise SafeFailure("project_id_invalid")
    directory = Path(directory)
    raw_values, parsed = validate_bundle(directory)
    if api is None:
        raise SafeFailure("cloud_api_unavailable")

    lock_path = directory / LOCK_NAME
    lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        lock_fd = os.open(lock_path, lock_flags, 0o600)
    except OSError:
        raise SafeFailure("private_lock_unavailable") from None
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        state = _read_state(directory)
        plans = _preflight(api, project, raw_values)
        password_status = _password_state(
            api, project, directory, parsed["db-bootstrap.json"]["password"],
            state, initialize,
        )
        versions = {}
        already_present = []
        for secret_id, plan in plans.items():
            if plan["version"] is not None:
                version = plan["version"].rsplit("/", 1)[-1]
                if not re.fullmatch(r"[1-9][0-9]*", version):
                    raise SafeFailure("secret_version_name_invalid")
                versions[secret_id] = version
                already_present.append(secret_id)
            else:
                versions[secret_id] = _publish_version(
                    api, project, secret_id, raw_values[plan["filename"]]
                )
        return {
            "event": "secret_publish_complete",
            "project": project,
            "instance": INSTANCE,
            "postgres_password": password_status,
            "versions": versions,
            "versions_reused": sorted(already_present),
        }
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _access_token(project):
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token", "--project", project],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SafeFailure("gcloud_auth_unavailable") from None
    token = result.stdout.strip()
    if result.returncode != 0 or not token or "\n" in token:
        raise SafeFailure("gcloud_auth_unavailable")
    return token


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Dedicated Lab 07 sandbox project ID")
    parser.add_argument("--bundle", required=True, help="Path to the mode-700 private bundle directory")
    parser.add_argument(
        "--initialize-postgres-password", action="store_true",
        help="Required only to authorize the first password set on this new lab instance",
    )
    args = parser.parse_args(argv)
    try:
        result = publish(
            args.project, args.bundle,
            initialize=args.initialize_postgres_password,
            api=GoogleAPI(_access_token(args.project)),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except SafeFailure as exc:
        print(json.dumps({"event": "secret_publish_failed", "reason": exc.reason}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
