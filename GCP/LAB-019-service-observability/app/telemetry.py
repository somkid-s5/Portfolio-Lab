from __future__ import annotations

import json
import os
import re
import sys
import uuid
from typing import Any

TRACE_HEADER = re.compile(r"^([0-9a-fA-F]{32})/([0-9]+)(?:;.*)?$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
EXPECTED_4XX = {400, 404, 409, 422}


def classify_request(method: str, path: str, status: int) -> tuple[bool, str]:
    """Count only task API business requests; expected client errors are excluded."""
    is_business = (method == "POST" and path == "/tasks") or (
        method == "GET" and path.startswith("/tasks/")
    )
    if not is_business or status in EXPECTED_4XX:
        return False, "excluded"
    return True, "bad" if status >= 500 else "good"


def emit_event(event: dict[str, Any], trace_header: str | None = None) -> None:
    payload: dict[str, Any] = {"severity": "INFO", **event}
    if trace_header:
        match = TRACE_HEADER.match(trace_header)
        if match:
            payload["logging.googleapis.com/trace"] = (
                f"projects/{os.environ.get('GOOGLE_CLOUD_PROJECT', 'unknown')}/traces/{match.group(1)}"
            )
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), file=sys.stdout, flush=True)


def request_id(candidate: str | None) -> str:
    if candidate and REQUEST_ID.fullmatch(candidate):
        return candidate
    return str(uuid.uuid4())
