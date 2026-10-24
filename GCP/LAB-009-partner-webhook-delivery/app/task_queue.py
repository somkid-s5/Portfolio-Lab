"""Cloud Tasks adapter: deterministic task names and OIDC-authenticated POSTs."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import tasks_v2
from google.protobuf import duration_pb2

from app.domain import (
    ValidationError,
    task_payload,
    task_resource_name,
)


_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class TaskNameConflict(RuntimeError):
    """A deterministic task name exists but cannot be confirmed as expected."""


@dataclass(frozen=True)
class PartnerQueue:
    project_id: str
    location_id: str
    queue_id: str
    partner_id: str
    worker_url: str
    task_service_account: str
    oidc_audience: str


@dataclass(frozen=True)
class EnqueueResult:
    task_name: str
    outcome: str  # created, already_exists, or missing_after_already_exists


def _validate_config(config: PartnerQueue) -> str:
    if not isinstance(config, PartnerQueue):
        raise ValidationError("partner queue configuration is required")
    if not isinstance(config.project_id, str) or not re.fullmatch(
        r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$", config.project_id
    ):
        raise ValidationError("project_id is invalid")
    if not isinstance(config.location_id, str) or not re.fullmatch(
        r"^[a-z0-9-]{1,63}$", config.location_id
    ):
        raise ValidationError("location_id is invalid")
    if not isinstance(config.queue_id, str) or not re.fullmatch(
        r"^[A-Za-z0-9_-]{1,100}$", config.queue_id
    ):
        raise ValidationError("queue_id is invalid")
    if config.queue_id != config.partner_id:
        raise ValidationError("queue_id must match the partner allowlist entry")
    queue_parent = (
        f"projects/{config.project_id}/locations/{config.location_id}/queues/{config.queue_id}"
    )
    # Reuse the shared identifier constraints before sending a request.
    task_resource_name(
        config.project_id,
        config.location_id,
        config.queue_id,
        "0" * 64,
        1,
    )
    if not isinstance(config.partner_id, str) or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?", config.partner_id
    ):
        raise ValidationError("partner_id is invalid")
    parsed = urlsplit(config.worker_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/internal/deliver"
    ):
        raise ValidationError("worker_url must be the fixed HTTPS delivery route")
    audience = urlsplit(config.oidc_audience)
    if (
        audience.scheme != "https"
        or not audience.hostname
        or audience.username is not None
        or audience.password is not None
        or audience.port is not None
        or audience.query
        or audience.fragment
        or audience.path not in ("", "/")
        or audience.hostname != parsed.hostname
    ):
        raise ValidationError("OIDC audience must be the HTTPS Cloud Run service URL")
    if not isinstance(config.task_service_account, str) or not _EMAIL.fullmatch(
        config.task_service_account
    ):
        raise ValidationError("task service account must be an email address")
    if config.task_service_account.split("@", 1)[1].lower() != (
        f"{config.project_id}.iam.gserviceaccount.com"
    ):
        raise ValidationError("task service account must belong to the queue project")
    return queue_parent


def validate_partner_queue(config: PartnerQueue) -> str:
    """Validate non-secret queue configuration before service startup."""
    return _validate_config(config)


class CloudTasksEnqueuer:
    """Create deterministic HTTP tasks and resolve duplicate-name outcomes."""

    def __init__(self, client: Any, *, timeout_seconds: float = 10.0) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds


    def task_exists(self, task_name: str) -> bool:
        """Check only existence using Cloud Tasks BASIC view."""
        if not isinstance(task_name, str) or not re.fullmatch(
            r"^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/locations/[a-z0-9-]{1,63}/queues/[A-Za-z0-9_-]{1,100}/tasks/d-[0-9a-f]{32}-g[1-9][0-9]*$",
            task_name,
        ):
            raise ValidationError("task_name is invalid")
        try:
            task = self._client.get_task(
                name=task_name,
                timeout=self._timeout_seconds,
            )
        except NotFound:
            return False
        if getattr(task, "name", None) != task_name:
            raise TaskNameConflict("GetTask returned a different task name")
        return True

    def enqueue(
        self,
        event: Mapping[str, Any],
        *,
        delivery: str,
        generation: int,
        config: PartnerQueue,
    ) -> EnqueueResult:
        queue_parent = validate_partner_queue(config)
        payload = task_payload(event, delivery, generation)
        if payload["partner_id"] != config.partner_id:
            raise ValidationError("event partner_id does not match the configured queue")
        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        task_name = task_resource_name(
            config.project_id,
            config.location_id,
            config.queue_id,
            delivery,
            generation,
        )
        task = tasks_v2.Task(
            name=task_name,
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=config.worker_url,
                headers={"Content-Type": "application/json"},
                body=body,
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=config.task_service_account,
                    audience=config.oidc_audience,
                ),
            ),
            dispatch_deadline=duration_pb2.Duration(seconds=30),
        )
        try:
            self._client.create_task(
                parent=queue_parent,
                task=task,
                timeout=self._timeout_seconds,
            )
            return EnqueueResult(task_name=task_name, outcome="created")
        except AlreadyExists:
            try:
                existing = self._client.get_task(
                    name=task_name,
                    timeout=self._timeout_seconds,
                )
            except NotFound:
                # The task could have been dispatched/deleted between requests.
                # The caller must preserve the ledger and let the reconciler flag
                # the ambiguous result instead of recreating the same name.
                return EnqueueResult(
                    task_name=task_name,
                    outcome="missing_after_already_exists",
                )
            if getattr(existing, "name", None) != task_name:
                raise TaskNameConflict("GetTask returned a different task name")
            return EnqueueResult(task_name=task_name, outcome="already_exists")
