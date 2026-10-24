"""Private Cloud Tasks HTTP target; Cloud Run IAM authenticates the caller."""
from __future__ import annotations

import json
import logging

from flask import Flask, jsonify, request

from app.worker import DeliveryWorker


def create_worker_app(*, worker: DeliveryWorker) -> Flask:
    app = Flask("lab09-delivery-worker")
    app.config["MAX_CONTENT_LENGTH"] = 1024
    app.logger.setLevel(logging.INFO)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"}), 200

    @app.post("/internal/deliver")
    def deliver():
        if request.mimetype != "application/json":
            return jsonify({"error": "application_json_required"}), 415
        raw_body = request.get_data(cache=False)
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return jsonify({"error": "invalid_task"}), 400
        if not isinstance(payload, dict):
            return jsonify({"error": "invalid_task"}), 400
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if raw_body != canonical:
            return jsonify({"error": "invalid_task"}), 400
        result = worker.process(payload)
        response = jsonify(dict(result.body))
        response.status_code = result.status_code
        for name, value in (result.headers or {}).items():
            response.headers[name] = value
        return response

    return app
