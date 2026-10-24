"""Allowlisted WSGI launcher for the shared non-root Lab 09 image."""
from __future__ import annotations

import os
import re
import sys


SERVICE_MODULES = {
    "event-api": "app.event_service:app",
    "reconciler": "app.reconciler_service:app",
    "worker": "app.worker_service:app",
    "simulator": "app.simulator_service:app",
}


def build_command(role: str, port: str | int = "8080") -> list[str]:
    if role not in SERVICE_MODULES:
        raise ValueError("LAB09_SERVICE_ROLE must be one of the fixed service roles")
    port_text = str(port)
    if not re.fullmatch(r"[0-9]{1,5}", port_text) or not 1 <= int(port_text) <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    return [
        sys.executable,
        "-m",
        "gunicorn",
        "--bind",
        f"0.0.0.0:{port_text}",
        "--workers",
        "1",
        "--threads",
        "8",
        "--timeout",
        "20",
        "--graceful-timeout",
        "5",
        "--access-logfile",
        "-",
        "--error-logfile",
        "-",
        SERVICE_MODULES[role],
    ]


def main() -> None:
    role = os.environ.get("LAB09_SERVICE_ROLE", "")
    port = os.environ.get("PORT", "8080")
    try:
        command = build_command(role, port)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()
