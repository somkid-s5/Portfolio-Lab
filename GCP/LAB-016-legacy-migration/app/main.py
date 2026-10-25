from __future__ import annotations

import json
import logging
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import psycopg

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
ORDER_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_BODY = 4096


def connect_db():
    host = os.getenv("DB_HOST", "127.0.0.1")
    return psycopg.connect(
        host=host,
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "orders"),
        user=os.getenv("DB_USER", "orders_app"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=5,
        application_name="lab016-orders-api",
    )


def backend_name() -> str:
    return os.getenv("BACKEND_NAME", "unset")


def writes_enabled() -> bool:
    return os.getenv("ALLOW_WRITES", "true").strip().lower() in {"1", "true", "yes"}


def summary(conn) -> dict:
    row = conn.execute(
        "SELECT count(*)::bigint, COALESCE(sum(amount_cents), 0)::bigint, "
        "COALESCE(max(id), 0)::bigint FROM orders"
    ).fetchone()
    sequence = conn.execute("SELECT last_value, is_called FROM public.orders_id_seq").fetchone()
    by_status = conn.execute(
        "SELECT status, count(*)::bigint FROM orders GROUP BY status ORDER BY status"
    ).fetchall()
    return {
        "count": row[0],
        "total_amount_cents": row[1],
        "max_id": row[2],
        "sequence_last_value": sequence[0],
        "sequence_is_called": sequence[1],
        "by_status": {name: count for name, count in by_status},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "OrdersLab/1.0"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        path = urlsplit(self.path).path
        logging.info(json.dumps({
            "event": "http_access",
            "client": self.client_address[0],
            "method": self.command,
            "path": path,
            "message": fmt % args,
            "backend": backend_name(),
        }, ensure_ascii=False))

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._send(200, {"status": "ok", "backend": backend_name()})
            return
        if path == "/ops/backend":
            self._send(200, {"backend": backend_name()})
            return
        try:
            with connect_db() as conn:
                if path == "/readyz":
                    conn.execute("SELECT 1").fetchone()
                    self._send(200, {"status": "ready", "backend": backend_name()})
                    return
                if path == "/ops/summary":
                    data = summary(conn)
                    data["backend"] = backend_name()
                    self._send(200, data)
                    return
                if path == "/v1/orders":
                    query = parse_qs(urlsplit(self.path).query)
                    try:
                        limit = int(query.get("limit", ["20"])[0])
                    except (TypeError, ValueError):
                        self._send(400, {"error": "invalid_limit"})
                        return
                    if not 1 <= limit <= 100:
                        self._send(400, {"error": "limit_out_of_range"})
                        return
                    rows = conn.execute(
                        "SELECT id, order_ref, customer_name, amount_cents, status, created_at "
                        "FROM orders ORDER BY id DESC LIMIT %s",
                        (limit,),
                    ).fetchall()
                    self._send(200, {
                        "backend": backend_name(),
                        "count": len(rows),
                        "orders": [{
                            "id": r[0], "order_ref": r[1], "customer_name": r[2],
                            "amount_cents": r[3], "status": r[4], "created_at": r[5].isoformat(),
                        } for r in rows],
                    })
                    return
        except Exception as exc:
            logging.error(json.dumps({"event": "database_request_failed", "path": path,
                                      "error_type": type(exc).__name__, "backend": backend_name()}))
            self._send(503, {"error": "database_unavailable", "backend": backend_name()})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path != "/v1/orders":
            self._send(404, {"error": "not_found"})
            return
        if not writes_enabled():
            self._send(503, {"error": "writes_frozen", "backend": backend_name()})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, {"error": "invalid_content_length"})
            return
        if length < 1 or length > MAX_BODY:
            self._send(413, {"error": "body_size_out_of_range"})
            return
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self._send(415, {"error": "application_json_required"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self._send(400, {"error": "json_object_required"})
            return
        order_ref = payload.get("order_ref")
        customer = payload.get("customer_name")
        amount = payload.get("amount_cents")
        if not isinstance(order_ref, str) or not ORDER_REF.fullmatch(order_ref):
            self._send(400, {"error": "invalid_order_ref"})
            return
        if not isinstance(customer, str) or not customer.strip() or len(customer.strip()) > 100:
            self._send(400, {"error": "invalid_customer_name"})
            return
        if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= 100_000_000:
            self._send(400, {"error": "invalid_amount_cents"})
            return
        try:
            with connect_db() as conn:
                row = conn.execute(
                    "INSERT INTO orders (order_ref, customer_name, amount_cents, status) "
                    "VALUES (%s, %s, %s, 'NEW') "
                    "RETURNING id, order_ref, customer_name, amount_cents, status, created_at",
                    (order_ref, customer.strip(), amount),
                ).fetchone()
            self._send(201, {
                "backend": backend_name(),
                "order": {"id": row[0], "order_ref": row[1], "customer_name": row[2],
                          "amount_cents": row[3], "status": row[4], "created_at": row[5].isoformat()},
            })
        except psycopg.errors.UniqueViolation:
            self._send(409, {"error": "order_ref_already_exists"})
        except Exception as exc:
            logging.error(json.dumps({"event": "database_write_failed",
                                      "error_type": type(exc).__name__, "backend": backend_name()}))
            self._send(503, {"error": "database_unavailable", "backend": backend_name()})


def main() -> None:
    address = ("0.0.0.0", int(os.getenv("PORT", "8080")))
    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    logging.info(json.dumps({"event": "server_start", "port": address[1], "backend": backend_name()}))
    server.serve_forever()


if __name__ == "__main__":
    main()
