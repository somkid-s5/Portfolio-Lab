"""Strict non-secret Cloud Run configuration loaders for Lab 09."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from app.domain import ValidationError
from app.task_queue import PartnerQueue, validate_partner_queue
from app.worker import PartnerEndpoint, validate_partner_endpoint


_MAX_CONFIG_BYTES = 16 * 1024


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def _load_entries(env_name: str, required_fields: set[str]) -> list[dict[str, str]]:
    raw = os.environ.get(env_name, "")
    if not raw or len(raw.encode("utf-8")) > _MAX_CONFIG_BYTES:
        raise ValidationError(f"{env_name} is missing or exceeds the configuration limit")
    try:
        values = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(f"{env_name} must be valid JSON without duplicate keys") from exc
    if not isinstance(values, list) or not 1 <= len(values) <= 2:
        raise ValidationError(f"{env_name} must contain one or two partner entries")
    entries = []
    partner_ids = set()
    for value in values:
        if (
            not isinstance(value, dict)
            or set(value) != required_fields
            or any(not isinstance(item, str) or not item for item in value.values())
        ):
            raise ValidationError(f"{env_name} entry fields are invalid")
        partner_id = value["partner_id"]
        if partner_id in partner_ids:
            raise ValidationError(f"{env_name} has duplicate partner IDs")
        partner_ids.add(partner_id)
        entries.append(dict(value))
    return entries


def load_project_id() -> str:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project_id):
        raise ValidationError("GOOGLE_CLOUD_PROJECT is missing or invalid")
    return project_id


def load_partner_queues() -> dict[str, PartnerQueue]:
    fields = {
        "project_id", "location_id", "queue_id", "partner_id",
        "worker_url", "task_service_account", "oidc_audience",
    }
    entries = _load_entries("LAB09_PARTNER_QUEUES_JSON", fields)
    result = {
        item["partner_id"]: PartnerQueue(**item)
        for item in entries
    }
    if any(item.project_id != load_project_id() for item in result.values()):
        raise ValidationError("all partner queues must use GOOGLE_CLOUD_PROJECT")
    for queue in result.values():
        validate_partner_queue(queue)
    return result


def load_partner_endpoints() -> dict[str, PartnerEndpoint]:
    fields = {"partner_id", "url", "secret_version"}
    entries = _load_entries("LAB09_PARTNER_ENDPOINTS_JSON", fields)
    result = {
        item["partner_id"]: PartnerEndpoint(**item)
        for item in entries
    }
    for endpoint in result.values():
        validate_partner_endpoint(endpoint)
    return result


def load_simulator_settings() -> tuple[str, str, str, str]:
    partner_id = os.environ.get("LAB09_PARTNER_ID", "")
    secret_version = os.environ.get("LAB09_SECRET_VERSION", "")
    receipt_bucket = os.environ.get("LAB09_RECEIPT_BUCKET", "")
    fault_mode = os.environ.get("LAB09_FAULT_MODE", "normal")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?", partner_id):
        raise ValidationError("LAB09_PARTNER_ID is invalid")
    if not re.fullmatch(
        r"projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/secrets/[A-Za-z0-9_-]{1,255}/versions/[1-9][0-9]*",
        secret_version,
    ):
        raise ValidationError("LAB09_SECRET_VERSION must pin a numbered version")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]", receipt_bucket):
        raise ValidationError("LAB09_RECEIPT_BUCKET is invalid")
    if fault_mode not in ("normal", "transient-503-first-two", "permanent-400", "accept-then-503-on-first"):
        raise ValidationError("LAB09_FAULT_MODE is invalid")
    return partner_id, secret_version, receipt_bucket, fault_mode
