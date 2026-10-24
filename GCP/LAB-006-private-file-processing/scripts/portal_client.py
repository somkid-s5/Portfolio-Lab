"""Bounded learner API client. Never logs credentials, cookies or capability bodies."""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import stat
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import (HTTPRedirectHandler, HTTPCookieProcessor,
                            ProxyHandler, Request, build_opener)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def origin(value, *, loopback_test=False):
    parts = urlsplit(value)
    if (not parts.hostname or parts.username or parts.password or parts.query or
            parts.fragment or parts.path not in ("", "/")):
        raise ValueError("invalid_origin")
    if loopback_test:
        if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("loopback_only")
    elif parts.scheme != "https" or parts.port not in (None, 443):
        raise ValueError("verified_https_required")
    return value.rstrip("/")


def read_logins(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("private_regular_file_required")
    info = path.stat()
    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("private_file_permissions_required")
    with path.open("rb") as handle:
        data = handle.read(65537)
    if len(data) > 65536:
        raise ValueError("login_file_too_large")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("invalid_logins")
    return value


class Client:
    def __init__(self, base_url, *, loopback_test=False):
        self.origin = origin(base_url, loopback_test=loopback_test)
        self.opener = build_opener(ProxyHandler({}), NoRedirect(),
                                   HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = None
        self.calls = 0

    def call(self, path, *, data=None, key=None):
        # Caller chooses only named Portal APIs, never a returned URL.
        if (not isinstance(path, str) or not re.fullmatch(r"/api/[A-Za-z0-9_/?=&.-]{1,200}", path) or
                ".." in path or "//" in path):
            raise ValueError("invalid_api_path")
        if self.calls >= 30:
            raise ValueError("request_budget_exceeded")
        headers = {"Accept": "application/json"}
        payload = None
        if data is not None:
            payload = json.dumps(data, separators=(",", ":")).encode()
            if len(payload) > 4096:
                raise ValueError("request_too_large")
            headers.update({"Content-Type": "application/json",
                            "X-CSRF-Token": self.csrf or ""})
        if key is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
                raise ValueError("invalid_idempotency_key")
            headers["Idempotency-Key"] = key
        self.calls += 1
        request = Request(self.origin + path, data=payload, headers=headers)
        try:
            response = self.opener.open(request, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            status = response.code
            body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("response_too_large")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("invalid_json_response")
        return status, value

    def login(self, username, password):
        if (not isinstance(username, str) or not isinstance(password, str) or
                not 1 <= len(username) <= 64 or not 1 <= len(password) <= 256):
            raise ValueError("invalid_login_input")
        status, value = self.call("/api/session")
        if status != 200 or not isinstance(value.get("csrf"), str):
            raise ValueError("session_failed")
        self.csrf = value["csrf"]
        status, value = self.call("/api/login", data={"username": username, "password": password})
        if status != 200 or value.get("user") != username or not isinstance(value.get("csrf"), str):
            raise ValueError("login_failed")
        self.csrf = value["csrf"]
