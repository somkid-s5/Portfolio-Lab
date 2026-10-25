"""Public synthetic partner endpoint; HMAC, freshness and receipts are mandatory."""
from __future__ import annotations

import logging

from flask import Flask, jsonify, request

from app.simulator import PartnerSimulator


def create_simulator_app(*, simulator: PartnerSimulator) -> Flask:
    app = Flask("lab09-partner-simulator")
    app.config["MAX_CONTENT_LENGTH"] = 8192
    app.logger.setLevel(logging.INFO)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"}), 200

    @app.post("/v1/webhooks/<partner_id>")
    def receive(partner_id: str):
        if request.mimetype != "application/json":
            return jsonify({"error": "application_json_required"}), 415
        if partner_id != simulator.partner_id:
            return jsonify({"error": "partner_not_found"}), 404
        raw_body = request.get_data(cache=False)
        status, headers, body = simulator.receive(raw_body, request.headers)
        response = jsonify(body)
        response.status_code = status
        for name, value in headers.items():
            response.headers[name] = value
        return response

    return app
