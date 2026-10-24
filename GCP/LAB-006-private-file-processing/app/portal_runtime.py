"""Cloud Run wiring: use attached service identity, never private-key files."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from retry_dispatch import NoRedirect, RetryDispatcher


class MetadataTokens:
    ROOT = ("http://metadata.google.internal/computeMetadata/v1/"
            "instance/service-accounts/default/")

    def __init__(self, *, opener=None):
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect())

    def _read(self, suffix):
        request = Request(self.ROOT + suffix, headers={"Metadata-Flavor": "Google"})
        with self.opener.open(request, timeout=3) as response:
            if response.headers.get("Metadata-Flavor") != "Google":
                raise ValueError("invalid_metadata_response")
            data = response.read(65537)
        if len(data) > 65536:
            raise ValueError("metadata_response_too_large")
        return data

    def access_token(self):
        value = json.loads(self._read("token"))
        token = value.get("access_token")
        if (not isinstance(token, str) or not token or
                any(c.isspace() for c in token) or value.get("token_type") != "Bearer"):
            raise ValueError("invalid_access_token")
        return token

    def id_token(self, audience):
        RetryDispatcher(audience, lambda _: None)
        token = self._read("identity?" + urlencode({"audience": audience})).decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
            raise ValueError("invalid_identity_token")
        return token


def read_auth(path):
    with Path(path).open("rb") as handle:
        data = handle.read(65537)
    if len(data) > 65536:
        raise ValueError("auth_file_too_large")
    value = json.loads(data)
    if (not isinstance(value, dict) or set(value) != {"session_key", "users"} or
            not isinstance(value["session_key"], str) or
            not re.fullmatch(r"[a-f0-9]{64}", value["session_key"]) or
            not isinstance(value["users"], dict) or
            set(value["users"]) != {"alice", "bob", "operator"}):
        raise ValueError("invalid_auth_bundle")
    for name, user in value["users"].items():
        if (not isinstance(user, dict) or set(user) != {"password_hash", "role"} or
                user["role"] != ("operator" if name == "operator" else "customer") or
                not isinstance(user["password_hash"], str) or
                not user["password_hash"].startswith("scrypt:")):
            raise ValueError("invalid_auth_bundle")
    return value


def build_portal():
    from google.cloud import firestore, storage
    from firestore_jobs import Jobs
    from signed_access import Access
    from portal_http import create_app
    if any(os.environ.get(key) for key in (
            "FIRESTORE_EMULATOR_HOST", "STORAGE_EMULATOR_HOST",
            "GOOGLE_APPLICATION_CREDENTIALS")):
        raise ValueError("attached_service_identity_required")
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    if os.environ["FIRESTORE_DATABASE"] != "lab006-files":
        raise ValueError("explicit_lab_database_required")
    mode = os.environ.get("UPLOAD_LIMIT_MODE", "baseline")
    if mode not in ("baseline", "large"):
        raise ValueError("invalid_limit_mode")
    auth = read_auth(os.environ["AUTH_FILE"])
    client = firestore.Client(project=project, database="lab006-files")
    jobs = Jobs(client)
    tokens = MetadataTokens()
    access = Access(jobs, storage.Client(project=project),
                    os.environ["INCOMING_BUCKET"], os.environ["RESULTS_BUCKET"],
                    os.environ["UPLOAD_SIGNER"], os.environ["DOWNLOAD_SIGNER"],
                    tokens.access_token)
    dispatcher = RetryDispatcher(os.environ["WORKER_ORIGIN"], tokens.id_token)
    def health():
        client.collection("_health").document("probe").get(timeout=3)
    return create_app(jobs, access, auth, metadata_health=health,
                      limits=(1048576, 10000) if mode == "baseline" else (5242880, 50000),
                      retry_dispatch=dispatcher)
