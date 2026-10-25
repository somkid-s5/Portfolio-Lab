from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
from typing import Callable
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database import get_engine
from app.telemetry import emit_event


def create_worker_app(
    engine_factory: Callable[[], Engine] = get_engine,
    fault_mode: str | None = None,
    delay_ms: int | None = None,
) -> FastAPI:
    app = FastAPI(title="Lab 19 Task Worker", version="1.0.0")
    configured_fault = fault_mode if fault_mode is not None else os.getenv("WORKER_FAULT_MODE", "none")
    configured_delay = delay_ms
    if configured_delay is None:
        configured_delay = int(os.getenv("WORKER_DELAY_MS", "0"))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": "lab19-task-worker"}

    @app.post("/events", status_code=204)
    async def receive_push(envelope: dict, request: Request):
        try:
            encoded = envelope["message"]["data"]
            payload = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
            task_id = str(UUID(payload["task_id"]))
        except (KeyError, ValueError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
            emit_event({"event": "worker_invalid_message", "outcome": "poison"})
            raise HTTPException(status_code=400, detail="Invalid Pub/Sub push envelope") from exc

        if configured_fault == "503":
            emit_event({"event": "worker_task", "task_id": task_id, "outcome": "retryable_error"})
            raise HTTPException(status_code=503, detail="Lab fault: injected worker failure")
        if configured_fault == "slow":
            await asyncio.sleep(min(max(configured_delay, 0), 10000) / 1000)

        engine = engine_factory()
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT task_id, status, payload
                    FROM lab19.tasks
                    WHERE task_id = :task_id
                    FOR UPDATE
                    """
                ),
                {"task_id": task_id},
            ).mappings().first()

            if row is None:
                emit_event({"event": "worker_task", "task_id": task_id, "outcome": "orphan_ack"})
                return Response(status_code=204)

            if row["status"] == "SUCCEEDED":
                emit_event({"event": "worker_task", "task_id": task_id, "outcome": "duplicate_ack"})
                return Response(status_code=204)

            task_payload = row["payload"]
            if isinstance(task_payload, str):
                task_payload = json.loads(task_payload)
            total_cents = sum(
                item["quantity"] * item["unit_price_cents"]
                for item in task_payload["items"]
            )
            result = json.dumps(
                {"line_count": len(task_payload["items"]), "total_cents": total_cents},
                separators=(",", ":"),
            )
            connection.execute(
                text(
                    """
                    UPDATE lab19.tasks
                    SET status = 'SUCCEEDED',
                        result = CAST(:result AS JSONB),
                        completed_at = now()
                    WHERE task_id = :task_id
                    """
                ),
                {"task_id": task_id, "result": result},
            )

        emit_event({"event": "worker_task", "task_id": task_id, "outcome": "succeeded"})
        return Response(status_code=204)

    return app


app = create_worker_app()
