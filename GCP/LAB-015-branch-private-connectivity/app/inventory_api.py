"""Synthetic read-only Inventory API for private path and IAM checks."""
from __future__ import annotations

import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

ITEMS = (
    {"sku": "SKU-100", "name": "USB-C Dock", "available": 17, "warehouse": "BKK-01"},
    {"sku": "SKU-200", "name": "Wireless Keyboard", "available": 42, "warehouse": "BKK-01"},
    {"sku": "SKU-300", "name": "Conference Camera", "available": 6, "warehouse": "CNX-01"},
)


def json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def create_handler():
    class InventoryHandler(BaseHTTPRequestHandler):
        server_version = "Lab015Inventory/1.0"

        def _send(self, status: int, payload: dict) -> None:
            body = json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            request_id = self.headers.get("X-Request-Id", str(uuid.uuid4()))
            self.request_id = request_id
            parsed = urlsplit(self.path)
            if parsed.path == "/healthz":
                self._send(200, {"status": "ok", "service": "lab015-inventory", "request_id": request_id})
                return
            if parsed.path == "/":
                self._send(200, {"service": "lab015-inventory", "endpoints": ["/healthz", "/v1/items"]})
                return
            if parsed.path == "/v1/items":
                sku_values = parse_qs(parsed.query).get("sku", [])
                selected = [item for item in ITEMS if not sku_values or item["sku"] == sku_values[0]]
                self._send(200, {"items": selected, "count": len(selected), "request_id": request_id})
                return
            if parsed.path.startswith("/v1/items/"):
                sku = unquote(parsed.path.removeprefix("/v1/items/"))
                found = next((item for item in ITEMS if item["sku"] == sku), None)
                if found is None:
                    self._send(404, {"error": "item_not_found", "request_id": request_id})
                    return
                self._send(200, {"item": found, "request_id": request_id})
                return
            self._send(404, {"error": "not_found", "request_id": request_id})

        def do_POST(self) -> None:
            self.request_id = str(uuid.uuid4())
            self._send(405, {"error": "read_only_api", "request_id": self.request_id})

        def log_request(self, code="-", size="-") -> None:
            parsed = urlsplit(self.path)
            print(json.dumps({
                "severity": "INFO",
                "request_id": getattr(self, "request_id", ""),
                "method": self.command,
                "path": parsed.path,
                "status": code,
            }, separators=(",", ":")), flush=True)

        def log_message(self, _format, *_args) -> None:
            return

    return InventoryHandler


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), create_handler())
    print(json.dumps({"severity": "INFO", "message": "inventory API started", "port": port}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
