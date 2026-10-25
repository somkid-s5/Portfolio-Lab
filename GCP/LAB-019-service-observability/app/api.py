from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database import get_engine
from app.pubsub import publish_task
from app.telemetry import classify_request, emit_event, request_id as make_request_id


class TaskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9-]+$")
    quantity: int = Field(ge=1, le=100)
    unit_price_cents: int = Field(ge=1, le=1000000)


class CreateTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    items: list[TaskItem] = Field(min_length=1, max_length=20)


def create_app(
    engine_factory: Callable[[], Engine] = get_engine,
    publisher: Callable[[str], None] = publish_task,
    fault_mode: str | None = None,
    fault_delay_ms: int | None = None,
) -> FastAPI:
    app = FastAPI(title="Lab 19 Task API", version="1.0.0")
    configured_fault = fault_mode if fault_mode is not None else os.getenv("API_FAULT_MODE", "none")
    configured_delay = fault_delay_ms
    if configured_delay is None:
        configured_delay = int(os.getenv("API_FAULT_DELAY_MS", "1200"))

    @app.middleware("http")
    async def record_business_request(request: Request, call_next):
        start = time.perf_counter()
        request.state.request_id = make_request_id(request.headers.get("x-request-id"))
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            eligible, outcome = classify_request(request.method, request.url.path, status)
            event = {
                "event": "business_request",
                "request_id": request.state.request_id,
                "task_id": getattr(request.state, "task_id", None),
                "route": "tasks" if request.url.path == "/tasks" or request.url.path.startswith("/tasks/") else "other",
                "method": request.method,
                "status_code": status,
                "eligible": eligible,
                "outcome": outcome,
                "duration_ms": duration_ms,
            }
            emit_event(event, request.headers.get("x-cloud-trace-context"))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": "lab19-task-api"}

    @app.post("/tasks", status_code=202)
    async def create_task(body: CreateTask, request: Request):
        if configured_fault == "5xx":
            raise HTTPException(status_code=503, detail="Lab fault: injected API failure")
        if configured_fault == "slow":
            await asyncio.sleep(min(max(configured_delay, 0), 3000) / 1000)

        task_id = str(uuid4())
        payload_json = json.dumps(body.model_dump(mode="json"), separators=(",", ":"))
        engine = engine_factory()
        with engine.begin() as connection:
            inserted = connection.execute(
                text(
                    """
                    INSERT INTO lab19.tasks
                        (task_id, idempotency_key, payload, status, created_at)
                    VALUES
                        (:task_id, :key, CAST(:payload AS JSONB), 'QUEUED', now())
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING task_id, status, created_at
                    """
                ),
                {"task_id": task_id, "key": body.idempotency_key, "payload": payload_json},
            ).mappings().first()
            if inserted:
                task = dict(inserted)
            else:
                existing = connection.execute(
                    text(
                        """
                        SELECT task_id, status, created_at
                        FROM lab19.tasks
                        WHERE idempotency_key = :key
                        """
                    ),
                    {"key": body.idempotency_key},
                ).mappings().one()
                task = dict(existing)

        stable_task_id = str(task["task_id"])
        request.state.task_id = stable_task_id
        if task["status"] == "QUEUED":
            try:
                publisher(stable_task_id)
            except Exception as exc:
                emit_event(
                    {
                        "event": "task_publish_failed",
                        "request_id": request.state.request_id,
                        "task_id": stable_task_id,
                        "error_type": type(exc).__name__,
                    }
                )
                raise HTTPException(
                    status_code=503,
                    detail="Queue publish failed; retry using the same idempotency key",
                ) from exc

        return JSONResponse(
            status_code=202,
            content={
                "task_id": stable_task_id,
                "status": task["status"],
                "created_at": task["created_at"].isoformat(),
                "idempotent_replay": not bool(inserted),
            },
        )

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str, request: Request):
        with engine_factory().connect() as connection:
            result = connection.execute(
                text(
                    """
                    SELECT task_id, status, result, created_at, completed_at
                    FROM lab19.tasks
                    WHERE task_id = :task_id
                    """
                ),
                {"task_id": task_id},
            ).mappings().first()
        if result is None:
            raise HTTPException(status_code=404, detail="Task not found")
        request.state.task_id = task_id
        return {
            "task_id": str(result["task_id"]),
            "status": result["status"],
            "result": result["result"],
            "created_at": result["created_at"].isoformat(),
            "completed_at": result["completed_at"].isoformat() if result["completed_at"] else None,
        }

    return app


app = create_app()
