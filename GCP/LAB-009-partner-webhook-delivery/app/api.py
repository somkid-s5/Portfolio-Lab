"""Authenticated Event API routes; Cloud Run IAM enforces caller identity."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Mapping
import uuid

from flask import Flask, jsonify, request

from app.domain import (
    ValidationError,
    build_event,
    delivery_id as make_delivery_id,
    parse_submission,
    payload_sha256,
    task_resource_name,
    validate_idempotency_key,
)
from app.ledger import FirestoreLedger, IdempotencyConflict, LedgerInvariantError
from app.task_queue import CloudTasksEnqueuer, PartnerQueue


UNKNOWN_TASK_REASON = "task_missing_after_already_exists"


def create_event_app(
    *,
    ledger: FirestoreLedger,
    enqueuer: CloudTasksEnqueuer,
    partner_queues: Mapping[str, PartnerQueue],
    clock: Callable[[], datetime] | None = None,
    event_id_factory: Callable[[], str] | None = None,
) -> Flask:
    """Build the Event API with injectable dependencies for emulator tests."""
    queues = dict(partner_queues)
    if not queues or any(key != value.partner_id for key, value in queues.items()):
        raise ValueError("partner queue keys must match configured partner IDs")
    now = clock or (lambda: datetime.now(timezone.utc))
    make_event_id = event_id_factory or (lambda: str(uuid.uuid4()))
    app = Flask("lab09-event-api")
    app.logger.setLevel(logging.INFO)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"}), 200

    @app.post("/v1/events")
    def submit_event():
        request_id = uuid.uuid4().hex
        if request.mimetype != "application/json":
            return jsonify({"error": "application_json_required"}), 415

        raw_body = request.get_data(cache=False)
        try:
            idempotency_key = validate_idempotency_key(
                request.headers.get("Idempotency-Key", "")
            )
            submission = parse_submission(raw_body, tuple(queues))
        except ValidationError as exc:
            return jsonify({"error": "invalid_request", "message": str(exc)}), 400

        partner_id = submission["partner_id"]
        config = queues[partner_id]
        try:
            event = build_event(
                submission,
                event_id=make_event_id(),
                accepted_at=now(),
            )
            did = make_delivery_id(event["event_id"], partner_id)
            task_name = task_resource_name(
                config.project_id,
                config.location_id,
                config.queue_id,
                did,
                1,
            )
            accepted = ledger.accept(
                event,
                idempotency_key=idempotency_key,
                request_sha256=payload_sha256(raw_body),
                task_name=task_name,
            )
        except IdempotencyConflict:
            return jsonify({"error": "idempotency_conflict"}), 409
        except Exception as exc:
            app.logger.error(
                "event_accept_failed request_id=%s error_type=%s",
                request_id,
                type(exc).__name__,
            )
            return jsonify(
                {"error": "temporarily_unavailable", "request_id": request_id}
            ), 503

        # The Firestore transaction is the durable-acceptance boundary. All work
        # after it is best effort: a failure remains recoverable by Reconciler.
        try:
            delivery_record = ledger.get_delivery(accepted.delivery_id)
            event_record = ledger.get_event(accepted.event_id)
            if (
                delivery_record
                and delivery_record.get("status") == "enqueue_pending"
                and event_record
                and isinstance(event_record.get("event"), dict)
            ):
                generation = delivery_record.get("generation")
                task_event = event_record["event"]
                result = enqueuer.enqueue(
                    task_event,
                    delivery=accepted.delivery_id,
                    generation=generation,
                    config=queues[task_event["partner_id"]],
                )
                if result.outcome in ("created", "already_exists"):
                    ledger.mark_task_enqueued(
                        accepted.delivery_id,
                        generation=generation,
                        task_name=result.task_name,
                        now=now(),
                    )
                elif result.outcome == "missing_after_already_exists":
                    ledger.mark_retry_ended_unknown(
                        accepted.delivery_id,
                        generation=generation,
                        reason=UNKNOWN_TASK_REASON,
                        now=now(),
                    )
                else:
                    raise LedgerInvariantError("unexpected enqueue outcome")
        except Exception as exc:
            try:
                # Does not regress a state already advanced by a fast worker.
                record = ledger.get_delivery(accepted.delivery_id)
                if record and record.get("status") == "enqueue_pending":
                    ledger.record_enqueue_error(
                        accepted.delivery_id,
                        generation=record.get("generation"),
                        error_code=type(exc).__name__,
                        now=now(),
                    )
            except Exception:
                pass
            app.logger.warning(
                "event_enqueue_deferred request_id=%s event_id=%s delivery_id=%s partner_id=%s error_type=%s",
                request_id,
                accepted.event_id,
                accepted.delivery_id,
                partner_id,
                type(exc).__name__,
            )

        return jsonify(
            {
                "event_id": accepted.event_id,
                "delivery_id": accepted.delivery_id,
                "status": "accepted",
                "duplicate": accepted.duplicate,
            }
        ), 202

    return app
