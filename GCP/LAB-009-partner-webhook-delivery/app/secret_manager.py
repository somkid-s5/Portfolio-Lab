"""Bounded Secret Manager access that never logs secret payloads."""
from __future__ import annotations

from typing import Any
import re

from google.api_core.exceptions import FailedPrecondition, NotFound, PermissionDenied


class SecretConfigurationError(RuntimeError):
    """A pinned secret version is missing, disabled or not authorized."""


class SecretVersionReader:
    def __init__(self, client: Any, *, timeout_seconds: float = 5.0):
        self._client = client
        self._timeout = timeout_seconds

    def __call__(self, version_name: str) -> bytes:
        if not isinstance(version_name, str) or not re.fullmatch(
            r"projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/secrets/[A-Za-z0-9_-]{1,255}/versions/[1-9][0-9]*",
            version_name,
        ):
            raise ValueError("version_name must be a pinned Secret Manager version")
        try:
            response = self._client.access_secret_version(
                request={"name": version_name},
                timeout=self._timeout,
            )
        except (NotFound, PermissionDenied, FailedPrecondition) as exc:
            raise SecretConfigurationError("pinned secret version is unavailable") from exc
        payload = getattr(getattr(response, "payload", None), "data", None)
        if not isinstance(payload, bytes):
            raise RuntimeError("secret payload response is invalid")
        return payload
