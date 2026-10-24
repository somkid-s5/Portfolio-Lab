"""Small HTTP servers for the API edge and private quote worker."""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import logging
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .pricing import calculate_quote, validate_quote_request, validate_rules
from .secrets import access_secret


MAX_BODY_BYTES = 4096
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
LOG = logging.getLogger("quote-engine")


@dataclass(frozen=True)
class RuntimeConfig:
    api_token: str = ""
    pricing_rules: dict[str, Any] | None = None
    worker_url: str = ""
    worker_timeout_seconds: float = 2.0
    cpu_work_ms: int = 20


def load_config(role: str, secret_reader=access_secret) -> RuntimeConfig:
    if role == "api":
        token_id = os.environ.get("API_TOKEN_SECRET_ID", "api-bearer-token")
        token = secret_reader(token_id)
        if not token or len(token) > 512 or not token.isascii():
            raise RuntimeError("API token secret is empty or exceeds its configured limit")
        return RuntimeConfig(
            api_token=token,
            worker_url=os.environ.get(
                "QUOTE_WORKER_URL",
                "http://quote-worker.quote-platform.svc.cluster.local:8081",
            ),
        )
    if role == "worker":
        rules_id = os.environ.get("QUOTE_RULES_SECRET_ID", "quote-rules")
        try:
            rules = validate_rules(json.loads(secret_reader(rules_id)))
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError("pricing rules secret is not valid") from exc
        try:
            cpu_work_ms = int(os.environ.get("QUOTE_CPU_WORK_MS", "20"))
        except ValueError as exc:
            raise RuntimeError("QUOTE_CPU_WORK_MS must be an integer from 0 to 100") from exc
        if not 0 <= cpu_work_ms <= 100:
            raise RuntimeError("QUOTE_CPU_WORK_MS must be an integer from 0 to 100")
        return RuntimeConfig(pricing_rules=rules, cpu_work_ms=cpu_work_ms)
    raise ValueError("role must be api or worker")


def consume_cpu_budget(budget_ms: int) -> None:
    """Bounded deterministic CPU work used only to make HPA behavior observable."""
    if isinstance(budget_ms, bool) or not isinstance(budget_ms, int) or not 0 <= budget_ms <= 100:
        raise ValueError("CPU work budget must be an integer from 0 to 100 ms")
    deadline = time.thread_time_ns() + budget_ms * 1_000_000
    value = 17
    while time.thread_time_ns() < deadline:
        value = (value * 1_664_525 + 1_013_904_223) & 0xFFFFFFFF
    if value < 0:  # Keep the calculation observable without returning workload details.
        raise AssertionError("unreachable")


def _log(event: str, **fields: Any) -> None:
    LOG.info(json.dumps({"event": event, **fields}, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def make_handler(role: str, config: RuntimeConfig):
    if role not in {"api", "worker"}:
        raise ValueError("role must be api or worker")

    class QuoteHandler(BaseHTTPRequestHandler):
        server_version = "QuoteEngine"
        sys_version = ""

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

        def _request_id(self) -> str:
            candidate = self.headers.get("X-Request-ID", "")
            return candidate if REQUEST_ID_RE.fullmatch(candidate) else str(uuid4())

        def _body(self) -> Any:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except (TypeError, ValueError) as exc:
                raise ValueError("Content-Length is required") from exc
            if length < 1 or length > MAX_BODY_BYTES:
                raise ValueError(f"body size must be between 1 and {MAX_BODY_BYTES} bytes")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json")
            try:
                return json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("body must contain valid JSON") from exc

        def do_GET(self) -> None:
            if self.path in {"/", "/healthz", "/readyz"}:
                self._send(200, {"status": "ok", "role": role})
                return
            self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:
            started = time.monotonic()
            request_id = self._request_id()
            expected_path = "/v1/quotes" if role == "api" else "/internal/quote"
            if self.path != expected_path:
                self._send(404, {"error": "not_found", "request_id": request_id})
                return
            try:
                payload = self._body()
                if role == "api":
                    authorization = self.headers.get("Authorization", "")
                    supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
                    if not supplied or not hmac.compare_digest(supplied, config.api_token):
                        _log("quote_rejected", request_id=request_id, reason="unauthorized")
                        self._send(401, {"error": "unauthorized", "request_id": request_id})
                        return
                    validated = validate_quote_request(payload)
                    quote_id = str(uuid4())
                    worker_payload = {**validated, "quote_id": quote_id}
                    upstream_request = Request(
                        config.worker_url.rstrip("/") + "/internal/quote",
                        data=json.dumps(worker_payload, separators=(",", ":")).encode("utf-8"),
                        headers={"Content-Type": "application/json", "X-Request-ID": request_id},
                        method="POST",
                    )
                    with urlopen(upstream_request, timeout=config.worker_timeout_seconds) as upstream:
                        if upstream.status != 200:
                            raise RuntimeError("worker returned a non-success status")
                        result = json.loads(upstream.read(2048))
                    if not isinstance(result, dict) or result.get("quote_id") != quote_id:
                        raise RuntimeError("worker response did not match the request")
                    _log(
                        "quote_completed",
                        request_id=request_id,
                        rules_version=result.get("rules_version", "unknown"),
                        duration_ms=round((time.monotonic() - started) * 1000, 2),
                        outcome="success",
                    )
                    self._send(200, {"quote_id": quote_id, **result})
                    return

                if not isinstance(payload, dict) or not isinstance(payload.get("quote_id"), str):
                    raise ValueError("quote_id is required")
                consume_cpu_budget(config.cpu_work_ms)
                result = calculate_quote(payload, config.pricing_rules)
                _log(
                    "worker_quote_computed",
                    request_id=request_id,
                    quote_id=payload["quote_id"],
                    rules_version=result["rules_version"],
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                    outcome="success",
                )
                self._send(200, {"quote_id": payload["quote_id"], **result})
            except json.JSONDecodeError as exc:
                _log("quote_failed", request_id=request_id, reason="invalid_worker_response",
                     error_type=type(exc).__name__)
                self._send(503, {"error": "worker_unavailable", "request_id": request_id})
            except ValueError as exc:
                _log("quote_rejected", request_id=request_id, reason="invalid_request")
                self._send(400, {"error": str(exc), "request_id": request_id})
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
                reason = "worker_unavailable" if role == "api" else "worker_error"
                _log(
                    "quote_failed",
                    request_id=request_id,
                    reason=reason,
                    error_type=type(exc).__name__,
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
                self._send(503, {"error": reason, "request_id": request_id})

    return QuoteHandler


def serve(role: str, host: str, port: int) -> None:
    config = load_config(role)
    server = ThreadingHTTPServer((host, port), make_handler(role, config))
    server.daemon_threads = True
    _log("service_started", role=role, port=port)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
