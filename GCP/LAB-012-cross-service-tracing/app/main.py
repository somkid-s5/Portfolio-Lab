"""Synthetic checkout microservices with W3C trace propagation and safe JSON logs."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections import OrderedDict
from hmac import compare_digest
from typing import Any

import requests
from flask import Flask, jsonify, request
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

SKU_PATTERN = re.compile(r"^SKU-[0-9]{3}$")
CATALOG = {
    "SKU-001": {"sku": "SKU-001", "name": "Synthetic Cloud Notebook", "unit_price_thb": 1250, "available": True},
    "SKU-002": {"sku": "SKU-002", "name": "Synthetic Network Kit", "unit_price_thb": 890, "available": True},
}
MAX_QUANTITY = 5
PAYMENT_ATTEMPTS = 2
PAYMENT_TIMEOUT_SECONDS = 1.0
PAYMENT_SLOW_SECONDS = 1.7
PAYMENT_CACHE_SIZE = 256

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
LOGGER = logging.getLogger("lab012")
TRACER = trace.get_tracer("lab012.checkout")


def emit_event(event: str, **fields: Any) -> None:
    """Emit only bounded, non-sensitive fields and Cloud Logging trace correlation."""
    span_context = trace.get_current_span().get_span_context()
    record: dict[str, Any] = {"severity": "INFO", "event": event, **fields}
    if span_context.is_valid:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "")
        if project_id:
            record["logging.googleapis.com/trace"] = (
                f"projects/{project_id}/traces/{span_context.trace_id:032x}"
            )
        record["logging.googleapis.com/spanId"] = f"{span_context.span_id:016x}"
        record["logging.googleapis.com/trace_sampled"] = bool(span_context.trace_flags.sampled)
    LOGGER.info(json.dumps(record, separators=(",", ":"), sort_keys=True))


def configure_telemetry(app: Flask, role: str) -> None:
    """Install one OTLP/gRPC exporter and HTTP instrumentations in each service process."""
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "unknown-project")
    endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://otel-collector.checkout.svc.cluster.local:4317",
    )
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": role,
                "service.namespace": "checkout",
                "deployment.environment.name": "portfolio-lab",
                "cloud.provider": "gcp",
                "cloud.project.id": project_id,
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)
    RequestsInstrumentor().instrument()
    FlaskInstrumentor().instrument_app(app)


def _valid_checkout(payload: Any) -> tuple[str, int] | None:
    if not isinstance(payload, dict):
        return None
    sku = payload.get("sku")
    quantity = payload.get("quantity")
    if not isinstance(sku, str) or not SKU_PATTERN.fullmatch(sku):
        return None
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
        return None
    return sku, quantity


def create_app(role: str | None = None, *, telemetry: bool = False) -> Flask:
    role = role or os.getenv("SERVICE_ROLE", "storefront")
    if role not in {"storefront", "order", "catalog", "payment"}:
        raise ValueError("SERVICE_ROLE must be storefront, order, catalog, or payment")

    app = Flask(__name__)
    app.config["SERVICE_ROLE"] = role
    payment_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
    payment_lock = threading.Lock()

    if telemetry:
        configure_telemetry(app, role)

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", service=role), 200

    @app.get("/readyz")
    def readyz():
        return jsonify(status="ready", service=role), 200

    if role == "storefront":
        @app.post("/v1/checkout")
        def checkout():
            expected = os.getenv("DEMO_BEARER_TOKEN", "")
            supplied = request.headers.get("Authorization", "")
            if not expected or not supplied.startswith("Bearer ") or not compare_digest(
                supplied.removeprefix("Bearer "), expected
            ):
                emit_event("checkout_auth_denied", service=role, reason="invalid_or_missing_token")
                return jsonify(error="unauthorized"), 401

            parsed = _valid_checkout(request.get_json(silent=True))
            if parsed is None:
                return jsonify(error="invalid_checkout", max_quantity=MAX_QUANTITY), 400
            sku, quantity = parsed
            checkout_id = str(uuid.uuid4())
            with TRACER.start_as_current_span("checkout.submit") as span:
                span.set_attribute("checkout.sku", sku)
                span.set_attribute("checkout.quantity", quantity)
                try:
                    response = requests.post(
                        os.getenv("ORDER_URL", "http://order:8080/internal/checkout"),
                        json={"sku": sku, "quantity": quantity, "checkout_id": checkout_id},
                        timeout=4.0,
                    )
                    response.raise_for_status()
                    result = response.json()
                except requests.RequestException as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, "order_service_unavailable"))
                    emit_event("checkout_failed", service=role, dependency="order", error_type=type(exc).__name__)
                    trace_context = trace.get_current_span().get_span_context()
                    trace_id = f"{trace_context.trace_id:032x}" if trace_context.is_valid else None
                    return jsonify(error="checkout_unavailable", trace_id=trace_id), 502
            return jsonify(
                checkout_id=checkout_id,
                total_thb=result["total_thb"],
                currency=result.get("currency", "THB"),
                catalog_revision=result.get("catalog_revision", "legacy-v1"),
                trace_id=f"{trace.get_current_span().get_span_context().trace_id:032x}",
            ), 200

    elif role == "order":
        @app.post("/internal/checkout")
        def internal_checkout():
            parsed = _valid_checkout(request.get_json(silent=True))
            body = request.get_json(silent=True) or {}
            checkout_id = body.get("checkout_id")
            if parsed is None or not isinstance(checkout_id, str) or not checkout_id:
                return jsonify(error="invalid_checkout"), 400
            sku, quantity = parsed
            with TRACER.start_as_current_span("checkout.orchestrate") as root_span:
                root_span.set_attribute("checkout.sku", sku)
                root_span.set_attribute("checkout.quantity", quantity)
                api_version = os.getenv("CATALOG_API_VERSION", "v1")
                if api_version not in {"v1", "v2"}:
                    return jsonify(error="unsupported_catalog_version"), 500
                try:
                    with TRACER.start_as_current_span("catalog.lookup") as catalog_span:
                        catalog_response = requests.get(
                            f"{os.getenv('CATALOG_URL', 'http://catalog:8080')}/{api_version}/items/{sku}",
                            timeout=2.0,
                        )
                        catalog_response.raise_for_status()
                        item = catalog_response.json()
                        catalog_span.set_attribute("catalog.api_version", api_version)
                        catalog_span.set_attribute("catalog.sku", sku)
                except requests.RequestException as exc:
                    root_span.record_exception(exc)
                    root_span.set_status(Status(StatusCode.ERROR, "catalog_unavailable"))
                    emit_event("checkout_dependency_failed", service=role, dependency="catalog", error_type=type(exc).__name__)
                    return jsonify(error="catalog_unavailable"), 502

                if not item.get("available") or item.get("sku") != sku:
                    return jsonify(error="item_unavailable"), 409

                payment_ok = False
                for attempt in range(1, PAYMENT_ATTEMPTS + 1):
                    with TRACER.start_as_current_span("payment.authorize") as payment_span:
                        payment_span.set_attribute("payment.attempt", attempt)
                        payment_span.set_attribute("payment.max_attempts", PAYMENT_ATTEMPTS)
                        try:
                            payment_response = requests.post(
                                f"{os.getenv('PAYMENT_URL', 'http://payment:8080')}/authorize",
                                json={"idempotency_key": checkout_id, "amount_thb": item["unit_price_thb"] * quantity},
                                timeout=PAYMENT_TIMEOUT_SECONDS,
                            )
                            payment_response.raise_for_status()
                            payment_ok = bool(payment_response.json().get("approved"))
                            if not payment_ok:
                                raise requests.HTTPError("payment_not_approved")
                            payment_span.set_attribute("payment.result", "approved")
                            break
                        except requests.RequestException as exc:
                            payment_span.record_exception(exc)
                            payment_span.set_attribute("error.type", type(exc).__name__)
                            payment_span.set_status(Status(StatusCode.ERROR, "payment_attempt_failed"))
                            emit_event(
                                "payment_attempt_failed",
                                service=role,
                                dependency="payment",
                                attempt=attempt,
                                max_attempts=PAYMENT_ATTEMPTS,
                                error_type=type(exc).__name__,
                            )
                            if attempt < PAYMENT_ATTEMPTS:
                                time.sleep(0.1 * attempt)

                if not payment_ok:
                    root_span.set_status(Status(StatusCode.ERROR, "payment_unavailable"))
                    return jsonify(error="payment_unavailable", attempts=PAYMENT_ATTEMPTS), 503

                currency = item.get("currency", "THB")
                revision = item.get("catalog_revision", "legacy-v1")
                emit_event(
                    "checkout_completed",
                    service=role,
                    dependency="catalog+payment",
                    quantity=quantity,
                    catalog_api_version=api_version,
                )
                return jsonify(
                    checkout_id=checkout_id,
                    total_thb=item["unit_price_thb"] * quantity,
                    currency=currency,
                    catalog_revision=revision,
                ), 200

    elif role == "catalog":
        @app.get("/v1/items/<sku>")
        def catalog_v1(sku: str):
            item = CATALOG.get(sku)
            if item is None:
                return jsonify(error="not_found"), 404
            emit_event("catalog_read", service=role, api_version="v1")
            return jsonify(item), 200

        @app.get("/v2/items/<sku>")
        def catalog_v2(sku: str):
            if os.getenv("CATALOG_V2_ENABLED", "false").lower() != "true":
                return jsonify(error="not_found"), 404
            item = CATALOG.get(sku)
            if item is None:
                return jsonify(error="not_found"), 404
            emit_event("catalog_read", service=role, api_version="v2")
            return jsonify(
                **item,
                currency="THB",
                catalog_revision="2026-10-v2",
            ), 200

    elif role == "payment":
        @app.post("/authorize")
        def authorize():
            body = request.get_json(silent=True) or {}
            key = body.get("idempotency_key")
            amount = body.get("amount_thb")
            if not isinstance(key, str) or not key or isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
                return jsonify(error="invalid_payment_request"), 400
            mode = os.getenv("PAYMENT_MODE", "normal").lower()
            if mode == "unavailable":
                emit_event("payment_mock_unavailable", service=role, mode=mode)
                return jsonify(error="synthetic_unavailable"), 503
            if mode == "slow":
                time.sleep(PAYMENT_SLOW_SECONDS)
            elif mode != "normal":
                return jsonify(error="invalid_payment_mode"), 500

            with payment_lock:
                result = payment_cache.get(key)
                if result is None:
                    result = {"approved": True, "reference": uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:12]}
                    payment_cache[key] = result
                    while len(payment_cache) > PAYMENT_CACHE_SIZE:
                        payment_cache.popitem(last=False)
                payment_cache.move_to_end(key)
            emit_event("payment_mock_approved", service=role, mode=mode)
            return jsonify(result), 200

    return app


def create_runtime_app() -> Flask:
    """Gunicorn factory: initialize telemetry inside the serving worker."""
    return create_app(os.getenv("SERVICE_ROLE", "storefront"), telemetry=True)


if __name__ == "__main__":
    create_runtime_app().run(host="0.0.0.0", port=8080, threaded=True)
