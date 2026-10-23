"""Pure job transitions for execution inside metadata transactions.
Callers supply one UTC time and fresh token per transaction invocation.
No network I/O, randomness, clocks or storage side effects here.
"""
from copy import deepcopy
from datetime import timedelta
import re

TERMINAL = {"succeeded", "rejected", "expired"}
REASONS = {"invalid_utf8", "empty_file", "file_too_large", "invalid_header",
           "multiline_record", "invalid_columns", "field_too_long",
           "too_many_rows", "invalid_sale_id", "duplicate_sale_id",
           "invalid_sku", "invalid_integer", "integer_out_of_range",
           "total_overflow", "malformed_csv", "no_data_rows", "null_byte",
           "failed_integrity"}


class Conflict(ValueError):
    pass


def _time(now):
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("utc_time_required")


def new_job(job_id, owner, now, *, max_bytes=1048576, max_rows=10000,
            processor_version="v1"):
    _time(now)
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("invalid_job_id")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", owner):
        raise ValueError("invalid_owner")
    if ((max_bytes, max_rows) not in {(1048576, 10000), (5242880, 50000)} or
            not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", processor_version)):
        raise ValueError("invalid_contract")
    return {"job_id": job_id, "owner": owner,
            "object_name": f"incoming/{job_id}/source.csv",
            "created_at": now, "upload_deadline": now + timedelta(minutes=5),
            "expires_at": now + timedelta(hours=24),
            "delete_after": now + timedelta(hours=48),
            "max_bytes": max_bytes, "max_rows": max_rows,
            "processor_version": processor_version, "state": "awaiting_upload",
            "input_generation": None, "attempt_epoch": 0, "attempt_count": 0,
            "attempt_token": None, "lease_until": None, "safe_reason": None}


def claim(job, generation, token, now, *, finalized_at):
    """Returns (updated job, disposition). Must be committed atomically."""
    _time(now)
    _time(finalized_at)
    if not re.fullmatch(r"[1-9][0-9]{0,29}", generation):
        raise ValueError("invalid_generation")
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise ValueError("invalid_attempt_token")
    item = deepcopy(job)
    if item["input_generation"] not in (None, generation):
        return item, "ignored_generation"
    if item["state"] in TERMINAL:
        return item, "terminal"
    if now >= item["expires_at"]:
        item.update(state="expired", attempt_token=None, lease_until=None)
        return item, "terminal"
    if item["input_generation"] is None:
        # Transport may deliver late: use object finalization time, not receipt time.
        if (finalized_at < item["created_at"] or
                finalized_at > item["upload_deadline"]):
            item.update(state="expired", safe_reason="upload_deadline")
            return item, "terminal"
        item["input_generation"] = generation
    if item["state"] == "failed":
        return item, "needs_operator"
    if (item["state"] == "processing" and item["lease_until"] is not None and
            now < item["lease_until"]):
        return item, "busy"
    if item["attempt_count"] >= 5:
        item.update(state="failed", safe_reason="retry_budget",
                    attempt_token=None, lease_until=None)
        return item, "needs_operator"
    item.update(state="processing", attempt_count=item["attempt_count"] + 1,
                attempt_token=token, lease_until=now + timedelta(seconds=120),
                safe_reason=None)
    return item, "claimed"


def _owned_attempt(job, token, now):
    _time(now)
    if (job["state"] != "processing" or job["attempt_token"] != token or
            job["lease_until"] is None or now >= job["lease_until"]):
        raise Conflict("stale_attempt")
    if now >= job["expires_at"]:
        raise Conflict("job_expired")


def finish(job, token, now, *, output=None, reason=None):
    _owned_attempt(job, token, now)
    item = deepcopy(job)
    if (output is None) == (reason is None):
        raise ValueError("one_outcome_required")
    if reason is not None:
        if reason not in REASONS:
            raise ValueError("unsafe_reason")
        item.update(state="failed" if reason == "failed_integrity" else "rejected",
                    safe_reason=reason)
    else:
        expected = (f"results/{job['job_id']}/{job['input_generation']}/"
                    f"{job['processor_version']}/summary.json")
        if (set(output) != {"name", "generation", "sha256", "input_sha256"} or
                output["name"] != expected or
                not re.fullmatch(r"[1-9][0-9]{0,29}", output["generation"]) or
                any(not re.fullmatch(r"[a-f0-9]{64}", output[key])
                    for key in ("sha256", "input_sha256"))):
            raise ValueError("invalid_output_binding")
        item.update(state="succeeded", output_name=output["name"],
                    output_generation=output["generation"],
                    output_sha256=output["sha256"],
                    input_sha256=output["input_sha256"])
    item.update(attempt_token=None, lease_until=None, completed_at=now)
    return item


def release_transient(job, token, now):
    _owned_attempt(job, token, now)
    item = deepcopy(job)
    item.update(lease_until=now, safe_reason="transient_dependency")
    return item


def operator_retry(job, now):
    _time(now)
    item = deepcopy(job)
    if now >= item["expires_at"]:
        raise Conflict("job_expired")
    if (item["state"] != "failed" or item["safe_reason"] != "retry_budget" or
            item["input_generation"] is None or item["attempt_epoch"] >= 2):
        raise Conflict("retry_not_allowed")
    item.update(state="retry_pending", attempt_epoch=item["attempt_epoch"] + 1,
                attempt_count=0, attempt_token=None, lease_until=None,
                safe_reason=None)
    return item
