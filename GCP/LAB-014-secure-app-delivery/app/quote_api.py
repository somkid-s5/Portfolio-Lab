from __future__ import annotations

import json
import os
import re
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from flask import Flask, jsonify, request

ROUTES = {
    ("BKK", "CNX"): {"distance_km": Decimal("700"), "base_thb": Decimal("35.00")},
    ("BKK", "HKT"): {"distance_km": Decimal("840"), "base_thb": Decimal("35.00")},
}
RATE_PER_KG_KM = Decimal("0.12")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
MONEY = Decimal("0.01")


def _decimal_config(value: str) -> Decimal:
    try:
        factor = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise RuntimeError("QUOTE_PRICE_FACTOR must be a decimal between 0.50 and 2.00") from exc
    if not factor.is_finite() or not Decimal("0.50") <= factor <= Decimal("2.00"):
        raise RuntimeError("QUOTE_PRICE_FACTOR must be a decimal between 0.50 and 2.00")
    return factor


def _request_id() -> str:
    candidate = request.headers.get("X-Request-ID", "")
    return candidate if REQUEST_ID_RE.fullmatch(candidate) else uuid.uuid4().hex


def _log_event(event: str, **fields: Any) -> None:
    record = {"severity": "INFO", "event": event, **fields}
    print(json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True), flush=True)


def create_app(price_factor: str | None = None) -> Flask:
    factor = _decimal_config(price_factor if price_factor is not None else os.getenv("QUOTE_PRICE_FACTOR", "1.00"))
    app = Flask(__name__)
    app.config["QUOTE_PRICE_FACTOR"] = factor

    @app.before_request
    def assign_request_id():
        request.lab_request_id = _request_id()

    @app.after_request
    def attach_request_id(response):
        response.headers["X-Request-ID"] = request.lab_request_id
        return response

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok"), 200

    @app.get("/version")
    def version():
        return jsonify(
            app="shipping-quote-api",
            app_version=os.getenv("APP_VERSION", "local"),
            commit_sha=os.getenv("COMMIT_SHA", "unknown"),
            image_digest=os.getenv("IMAGE_DIGEST", "unknown"),
        ), 200

    @app.get("/api/v1/quote")
    def quote():
        origin = request.args.get("origin", "").strip().upper()
        destination = request.args.get("destination", "").strip().upper()
        weight_raw = request.args.get("weight_kg", "")

        route = ROUTES.get((origin, destination))
        if route is None:
            return jsonify(error="unsupported_route", message="Use BKK-CNX or BKK-HKT."), 400

        try:
            weight = Decimal(weight_raw)
        except (InvalidOperation, TypeError):
            return jsonify(error="invalid_weight", message="weight_kg must be a decimal number."), 400
        if not weight.is_finite() or not Decimal("0.10") <= weight <= Decimal("1000.00"):
            return jsonify(error="invalid_weight", message="weight_kg must be between 0.10 and 1000.00."), 400
        if max(0, -weight.as_tuple().exponent) > 3:
            return jsonify(error="invalid_weight_precision", message="weight_kg supports at most 3 decimal places."), 400

        total = (
            route["base_thb"]
            + route["distance_km"] * RATE_PER_KG_KM * weight * app.config["QUOTE_PRICE_FACTOR"]
        ).quantize(MONEY, rounding=ROUND_HALF_UP)
        request_id = request.lab_request_id
        _log_event(
            "quote.created",
            request_id=request_id,
            route=f"{origin}-{destination}",
            weight_kg=format(weight, "f"),
            amount_thb=format(total, ".2f"),
            commit_sha=os.getenv("COMMIT_SHA", "unknown"),
            image_digest=os.getenv("IMAGE_DIGEST", "unknown"),
        )
        return jsonify(
            request_id=request_id,
            origin=origin,
            destination=destination,
            distance_km=int(route["distance_km"]),
            weight_kg=format(weight, "f"),
            currency="THB",
            total_thb=format(total, ".2f"),
            pricing_version="v1",
        ), 200

    return app


app = create_app()
