"""Validated Cloud Run process entrypoint. No shell expansion of environment."""
import os


def command(environment):
    role = environment.get("SERVICE_ROLE")
    target = {"portal": "portal_runtime:build_portal()",
              "worker": "worker_http:build_app()"}.get(role)
    port = environment.get("PORT", "8080")
    if target is None or not isinstance(port, str) or not port.isascii() or not port.isdigit():
        raise ValueError("invalid_container_configuration")
    if not 1 <= int(port) <= 65535:
        raise ValueError("invalid_container_port")
    return ["/usr/local/bin/gunicorn", "--bind", "0.0.0.0:" + str(int(port)),
            "--workers", "1", "--threads", "8" if role == "portal" else "1",
            "--timeout", "65", "--graceful-timeout", "10",
            "--worker-tmp-dir", "/tmp", "--error-logfile", "-", target]


if __name__ == "__main__":
    try:
        arguments = command(os.environ)
    except ValueError:
        raise SystemExit("Invalid container configuration")
    os.execv(arguments[0], arguments)
