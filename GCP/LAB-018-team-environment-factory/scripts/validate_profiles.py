from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REQUIRED_LABELS = {"owner", "team", "cost_center", "managed_by", "environment"}


def _validate_environment(
    name: str,
    item: dict[str, Any],
    allowed_regions: set[str],
    base_labels: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    for key in ("project_id", "project_name", "region", "team_group", "labels", "budget"):
        if key not in item:
            errors.append(f"{name}: missing field {key}")

    project_id = item.get("project_id", "")
    if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
        errors.append(f"{name}: project_id must be 6-30 lowercase letters, digits or hyphens")
    region = item.get("region", "")
    if region not in allowed_regions:
        errors.append(f"{name}: region {region!r} is not in allowed_regions")

    group = item.get("team_group", "")
    if not isinstance(group, str) or not EMAIL_RE.fullmatch(group):
        errors.append(f"{name}: team_group must be a group email")
    contractor = item.get("contractor_group")
    if contractor is not None and (not isinstance(contractor, str) or not EMAIL_RE.fullmatch(contractor)):
        errors.append(f"{name}: contractor_group must be null or a group email")

    labels = dict(base_labels)
    extra_labels = item.get("labels", {})
    if isinstance(extra_labels, dict):
        labels.update(extra_labels)
    else:
        errors.append(f"{name}: labels must be an object")
    missing_labels = REQUIRED_LABELS - labels.keys()
    if missing_labels:
        errors.append(f"{name}: missing labels {', '.join(sorted(missing_labels))}")
    for key, value in labels.items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", str(key)):
            errors.append(f"{name}: invalid label key {key!r}")
        if not re.fullmatch(r"[a-z0-9_-]{0,63}", str(value)):
            errors.append(f"{name}: invalid label value for {key}")

    budget = item.get("budget", {})
    if not isinstance(budget, dict):
        errors.append(f"{name}: budget must be an object")
        budget = {}
    currency = budget.get("currency", "")
    units = budget.get("units")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        errors.append(f"{name}: budget.currency must be a three-letter ISO code")
    if not isinstance(units, int) or isinstance(units, bool) or units <= 0:
        errors.append(f"{name}: budget.units must be a positive whole number")
    thresholds = budget.get("thresholds", [])
    if not isinstance(thresholds, list) or not thresholds or any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0 or value > 2
        for value in thresholds
    ):
        errors.append(f"{name}: budget.thresholds must be greater than 0 and at most 2")
    email = budget.get("notification_email", "")
    if not isinstance(email, str) or not EMAIL_RE.fullmatch(email):
        errors.append(f"{name}: budget.notification_email must be an email address")
    return errors


def validate_profile(profile: dict[str, Any]) -> list[str]:
    allowed = profile.get("allowed_regions", [])
    if not isinstance(allowed, list) or not allowed or any(not isinstance(value, str) for value in allowed):
        return ["allowed_regions must be a non-empty array of region names"]
    environments = profile.get("environments", {})
    if not isinstance(environments, dict) or not environments:
        return ["environments must be a non-empty object"]
    base_labels = profile.get("labels", {})
    if not isinstance(base_labels, dict):
        return ["labels must be an object"]

    errors: list[str] = []
    project_ids: set[str] = set()
    for name, item in environments.items():
        if not isinstance(item, dict):
            errors.append(f"{name}: environment must be an object")
            continue
        errors.extend(_validate_environment(name, item, set(allowed), base_labels))
        project_id = item.get("project_id")
        if isinstance(project_id, str):
            if project_id in project_ids:
                errors.append(f"{name}: project_id is duplicated")
            project_ids.add(project_id)
        if item.get("environment") != name:
            errors.append(f"{name}: environment field must match its profile key")
    return errors


def validate_candidate(profile: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    errors = _validate_environment(
        "candidate",
        candidate,
        set(profile.get("allowed_regions", [])),
        profile.get("labels", {}),
    )
    reference = candidate.get("approval_reference", "")
    if not isinstance(reference, str) or not reference.strip() or reference.startswith("PENDING"):
        errors.append("candidate: approval_reference must contain the approved change record")
    if not candidate.get("contractor_group"):
        errors.append("candidate: contractor_group is required for this change request")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Lab 18 profiles without calling Google Cloud APIs.")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "environments.json",
    )
    parser.add_argument("--candidate", type=Path, help="Optional Change Request environment to validate.")
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        errors = validate_profile(profile)
        if args.candidate:
            candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
            errors.extend(validate_candidate(profile, candidate))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: unable to read profile: {type(exc).__name__}", file=sys.stderr)
        return 2

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print("Profile valid. No Google Cloud API was called.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
