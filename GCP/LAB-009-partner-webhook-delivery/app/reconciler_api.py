"""IAM-protected HTTP entrypoint for the bounded outbox reconciler.

Cloud Run IAM is the authentication boundary. Deploy this service privately and
grant roles/run.invoker only to the dedicated Cloud Scheduler caller identity.
"""
from __future__ import annotations

import json
import logging

from flask import Flask, jsonify, request

from app.domain import ValidationError
from app.reconciler import MAX_PAGE_SIZE, OutboxReconciler


def create_reconciler_app(
    *,
    reconciler: OutboxReconciler,
    page_size: int = MAX_PAGE_SIZE,
) -> Flask:
    """Create a Cloud Scheduler target with a fixed, bounded reconciliation page."""
    if (
        not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not 1 <= page_size <= MAX_PAGE_SIZE
    ):
        raise ValidationError("reconciler page size must be between 1 and 25")

    app = Flask("lab09-outbox-reconciler")
    app.config["MAX_CONTENT_LENGTH"] = 1024
    app.logger.setLevel(logging.INFO)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"}), 200

    @app.post("/internal/reconcile")
    def reconcile():
        raw_body = request.get_data(cache=False)
        if raw_body:
            if request.mimetype != "application/json":
                return jsonify({"error": "application_json_required"}), 415
            try:
                body = json.loads(raw_body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return jsonify({"error": "invalid_request"}), 400
            # Scheduler inputs are intentionally not an operator control plane.
            if not isinstance(body, dict) or body:
                return jsonify({"error": "unexpected_request_fields"}), 400

        try:
            summary = reconciler.run_once(page_size=page_size)
        except Exception as exc:
            app.logger.error(
                "reconciliation_failed error_type=%s",
                type(exc).__name__,
            )
            return jsonify({"error": "reconciliation_unavailable"}), 503

        result = {
            "pending_seen": summary.pending_seen,
            "queued_seen": summary.queued_seen,
            "running_seen": summary.running_seen,
            "enqueued": summary.enqueued,
            "moved_to_review": summary.moved_to_review,
            "errors": summary.errors,
        }
        app.logger.info(
            "reconciliation_summary pending_seen=%d queued_seen=%d running_seen=%d "
            "enqueued=%d moved_to_review=%d errors=%d",
            summary.pending_seen,
            summary.queued_seen,
            summary.running_seen,
            summary.enqueued,
            summary.moved_to_review,
            summary.errors,
        )
        if summary.errors:
            # A 5xx lets Cloud Scheduler retry; deterministic task names and
            # transactional state guards make replay safe.
            return jsonify({"status": "partial_failure", **result}), 503
        return jsonify({"status": "completed", **result}), 200

    return app
