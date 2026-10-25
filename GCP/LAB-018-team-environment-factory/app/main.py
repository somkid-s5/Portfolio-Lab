from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVICE_NAME = "lab18-status-api"


class StatusHandler(BaseHTTPRequestHandler):
    server_version = "Lab18StatusAPI"

    def do_GET(self) -> None:
        if self.path not in ("/", "/healthz"):
            self._log("other", 404)
            self._write_json(404, {"error": "not_found"})
            return
        environment = os.environ.get("ENVIRONMENT", "local")
        body = {
            "service": SERVICE_NAME,
            "environment": environment,
            "version": os.environ.get("APP_VERSION", "dev"),
            "status": "ok",
        }
        self._write_json(200, body)
        self._log("/healthz" if self.path == "/healthz" else "/", 200)

    def _write_json(self, status: int, body: dict[str, str]) -> None:
        encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _log(self, route: str, status: int) -> None:
        # Exclude headers, query strings, client addresses and request bodies.
        print(
            json.dumps(
                {
                    "severity": "INFO",
                    "message": "status_request",
                    "service": SERVICE_NAME,
                    "environment": os.environ.get("ENVIRONMENT", "local"),
                    "route": route,
                    "status_code": status,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stdout,
            flush=True,
        )

    def log_message(self, _format: str, *_args: object) -> None:
        # The default handler log includes client addresses and raw paths.
        return


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), StatusHandler).serve_forever()


if __name__ == "__main__":
    main()
