#!/usr/bin/env python3
"""Reconcile Batch task states and attempt outputs; publish only a complete manifest."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage
from lab13.contract import ContractError, parse_manifest_bytes, split_gs_uri


TASK_INDEX_RE = re.compile(r"(?:task-?)?([0-9]+)$")
OUTPUT_RE = re.compile(r"^runs/([a-z][a-z0-9-]{2,39})/shards/([0-9]{5})/attempt-([0-9]+)/result\.json$")


def normalize_tasks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("tasks"), list):
        return value["tasks"]
    raise ValueError("tasks JSON must be a list or an object with a tasks list")


def task_index(task: dict[str, Any]) -> int:
    name = str(task.get("name", "")).rstrip("/").split("/")[-1]
    match = TASK_INDEX_RE.fullmatch(name)
    if not match:
        raise ValueError(f"cannot identify task index from task name {name!r}")
    return int(match.group(1))


def evaluate(job: dict[str, Any], tasks_value: Any, manifest: dict[str, Any],
             outputs: list[tuple[str, bytes]], manifest_sha256: str | None = None) -> dict[str, Any]:
    tasks = normalize_tasks(tasks_value)
    expected = manifest["shard_count"]
    by_index: dict[int, dict[str, Any]] = {}
    issues: list[str] = []
    task_states: dict[str, str] = {}
    for task in tasks:
        index = task_index(task)
        if index in by_index:
            issues.append(f"duplicate Batch task index {index}")
        by_index[index] = task
    expected_indexes = set(range(expected))
    if set(by_index) != expected_indexes:
        issues.append(f"task indexes must be exactly 0..{expected - 1}")
    job_state = job.get("status", {}).get("state", "UNKNOWN")
    if job_state != "SUCCEEDED":
        issues.append(f"Batch job state is {job_state}, not SUCCEEDED")
    for index in sorted(expected_indexes):
        state = by_index.get(index, {}).get("status", {}).get("state", "MISSING")
        task_states[str(index)] = state
        if state != "SUCCEEDED":
            issues.append(f"task {index} state is {state}, not SUCCEEDED")
    outputs_by_shard: dict[int, list[dict[str, Any]]] = {}
    invalid_outputs: list[str] = []
    for object_name, raw in outputs:
        match = OUTPUT_RE.fullmatch(object_name)
        if not match:
            invalid_outputs.append(object_name)
            continue
        run_id, shard_text, attempt_text = match.groups()
        if run_id != manifest["run_id"]:
            continue
        try:
            result = json.loads(raw)
            shard_index = int(shard_text)
            attempt = int(attempt_text)
            expected_shard = manifest["shards"][shard_index]
            counts = (result.get("record_count"), result.get("units_total"), result.get("value_minor_total"))
            task = next((item for item in tasks if task_index(item) == shard_index), {})
            retry_codes = [
                event.get("taskExecution", {}).get("exitCode")
                for event in task.get("status", {}).get("statusEvents", [])
                if type(event.get("taskExecution", {}).get("exitCode")) is int
                and event.get("taskExecution", {}).get("exitCode") != 0
            ]
            if (type(result.get("schema_version")) is not int or result.get("schema_version") != 1 or result.get("run_id") != run_id
                    or result.get("shard_index") != shard_index or result.get("task_index") != shard_index
                    or type(result.get("attempt")) is not int or result.get("attempt") != attempt or attempt > 1
                    or type(result.get("shard_index")) is not int or type(result.get("task_index")) is not int
                    or any(code != 75 for code in retry_codes) or attempt != len(retry_codes)
                    or result.get("input_sha256") != expected_shard["sha256"]
                    or result.get("record_count") != expected_shard["record_count"]
                    or not isinstance(result.get("manifest_sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", result["manifest_sha256"])
                    or (manifest_sha256 is not None and result["manifest_sha256"] != manifest_sha256)
                    or any(type(value) is not int for value in counts)
                    or not expected_shard["record_count"] <= result["units_total"] <= expected_shard["record_count"] * 20
                    or not result["units_total"] <= result["value_minor_total"] <= expected_shard["record_count"] * 2_000_000_000):
                invalid_outputs.append(object_name)
                continue
            outputs_by_shard.setdefault(shard_index, []).append({
                "object": object_name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "result": result,
            })
        except (ValueError, TypeError, IndexError, KeyError, AttributeError):
            invalid_outputs.append(object_name)
    if invalid_outputs:
        issues.append("one or more attempt outputs have invalid names, JSON, or manifest bindings")
    selected: list[dict[str, Any]] = []
    for index in sorted(expected_indexes):
        matches = outputs_by_shard.get(index, [])
        if len(matches) != 1:
            issues.append(f"shard {index} must have exactly one validated successful result object; found {len(matches)}")
        else:
            selected.append(matches[0])
    complete = not issues and len(selected) == expected
    retry_exit_codes: dict[str, list[int]] = {}
    attempt_counts: dict[str, int] = {}
    for index in sorted(expected_indexes):
        task = by_index.get(index, {})
        codes = []
        for event in task.get("status", {}).get("statusEvents", []):
            exit_code = event.get("taskExecution", {}).get("exitCode")
            if type(exit_code) is int and exit_code != 0:
                codes.append(exit_code)
        retry_exit_codes[str(index)] = codes
        results = outputs_by_shard.get(index, [])
        successful_attempt = results[0]["result"]["attempt"] if len(results) == 1 else None
        attempt_counts[str(index)] = (successful_attempt + 1) if successful_attempt is not None else len(codes)
    return {
        "run_id": manifest["run_id"],
        "job_state": job_state,
        "task_count_expected": expected,
        "task_count_observed": len(tasks),
        "complete": complete,
        "issues": issues,
        "retry_exit_codes_by_task": retry_exit_codes,
        "attempt_count_by_task": attempt_counts,
        "task_state_by_index": task_states,
        "results": selected,
        "record_count": sum(item["result"]["record_count"] for item in selected),
        "units_total": sum(item["result"]["units_total"] for item in selected),
        "value_minor_total": sum(item["result"]["value_minor_total"] for item in selected),
    }


def make_completion_manifest(manifest_uri: str, attempt_output_bucket: str, manifest_raw: bytes, evaluated: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": evaluated["run_id"],
        "source_manifest_uri": manifest_uri,
        "source_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "task_count": evaluated["task_count_expected"],
        "record_count": evaluated["record_count"],
        "units_total": evaluated["units_total"],
        "value_minor_total": evaluated["value_minor_total"],
        "results": [
            {"uri": f"gs://{attempt_output_bucket}/{item['object']}", "sha256": item["sha256"],
             "shard_index": item["result"]["shard_index"], "attempt": item["result"]["attempt"],
             "record_count": item["result"]["record_count"]}
            for item in evaluated["results"]
        ],
    }


def render_report(evaluated: dict[str, Any], published_uri: str | None = None) -> str:
    rows = []
    result_by_index = {item["result"]["shard_index"]: item["result"] for item in evaluated["results"]}
    for index in range(evaluated["task_count_expected"]):
        result = result_by_index.get(index)
        state = evaluated["task_state_by_index"].get(str(index), "MISSING")
        codes = ", ".join(map(str, evaluated["retry_exit_codes_by_task"].get(str(index), []))) or "—"
        rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            index, html.escape(state),
            result.get("attempt") if result else "—",
            result.get("record_count") if result else "—",
            html.escape(codes),
        ))
    issues = "".join(f"<li>{html.escape(item)}</li>" for item in evaluated["issues"]) or "<li>All checks passed.</li>"
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lab 13 run {html.escape(evaluated['run_id'])}</title>
<style>body{{font:16px system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#172033}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd3dd;padding:.55rem;text-align:left}}th{{background:#eff4fa}}.ok{{color:#137333}}.bad{{color:#b3261e}}code{{overflow-wrap:anywhere}}</style>
<h1>Lab 13 — Reconciliation report</h1>
<p><strong>Run:</strong> <code>{html.escape(evaluated['run_id'])}</code></p>
<p><strong>Batch job:</strong> <code>{html.escape(evaluated['job_state'])}</code></p>
<p><strong>Reconciliation:</strong> <span class="{'ok' if evaluated['complete'] else 'bad'}">{'COMPLETE' if evaluated['complete'] else 'PARTIAL — DO NOT PUBLISH'}</span></p>
<p><strong>Records:</strong> {evaluated['record_count']} · <strong>Units:</strong> {evaluated['units_total']} · <strong>Synthetic value (minor units):</strong> {evaluated['value_minor_total']}</p>
<p><strong>Completion manifest:</strong> {html.escape(published_uri or 'not published')}</p>
<h2>Shard status</h2><table><thead><tr><th>Shard</th><th>State</th><th>Successful attempt</th><th>Rows</th><th>Failed exit codes</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Checks and blockers</h2><ul>{issues}</ul>
<p>Generated locally from submitted job/task JSON and Cloud Storage outputs. This report is not a performance benchmark.</p></html>
"""


def write_reports(directory: Path, evaluated: dict[str, Any], published_uri: str | None) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{evaluated['run_id']}-reconciliation.json"
    html_path = directory / f"{evaluated['run_id']}-reconciliation.html"
    payload = dict(evaluated)
    payload["published_manifest_uri"] = published_uri
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    html_path.write_text(render_report(evaluated, published_uri), encoding="utf-8")
    return json_path, html_path


def reconcile(job: dict[str, Any], tasks_value: Any, manifest_raw: bytes,
              output_objects: list[tuple[str, bytes]], manifest_uri: str,
              attempt_output_bucket: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = parse_manifest_bytes(manifest_raw)
    evaluated = evaluate(job, tasks_value, manifest, output_objects, hashlib.sha256(manifest_raw).hexdigest())
    completion = make_completion_manifest(manifest_uri, attempt_output_bucket, manifest_raw, evaluated) if evaluated["complete"] else {}
    return evaluated, completion


def completion_matches(existing: dict[str, Any], expected: dict[str, Any]) -> bool:
    immutable_fields = (
        "schema_version", "run_id", "source_manifest_uri", "source_manifest_sha256",
        "task_count", "record_count", "units_total", "value_minor_total", "results",
    )
    return all(existing.get(field) == expected.get(field) for field in immutable_fields)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-json", type=Path, required=True)
    parser.add_argument("--tasks-json", type=Path, required=True)
    parser.add_argument("--manifest-uri", required=True)
    parser.add_argument("--attempt-output-bucket", required=True)
    parser.add_argument("--published-bucket", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("work/reports"))
    parser.add_argument("--publish", action="store_true", help="create completion manifest only when every check passes")
    args = parser.parse_args()
    try:
        job = json.loads(args.job_json.read_text(encoding="utf-8"))
        tasks_value = json.loads(args.tasks_json.read_text(encoding="utf-8"))
        input_bucket, manifest_object = split_gs_uri(args.manifest_uri)
        client = storage.Client()
        manifest_blob = client.bucket(input_bucket).blob(manifest_object)
        manifest_raw = manifest_blob.download_as_bytes()
        manifest = parse_manifest_bytes(manifest_raw)
        output_bucket = client.bucket(args.attempt_output_bucket)
        outputs = [(blob.name, blob.download_as_bytes()) for blob in output_bucket.list_blobs(
            prefix=f"runs/{manifest['run_id']}/shards/")]
        evaluated, completion = reconcile(job, tasks_value, manifest_raw, outputs, args.manifest_uri,
                                          args.attempt_output_bucket)
        published_uri = None
        if evaluated["complete"] and args.publish:
            object_name = f"runs/{manifest['run_id']}/completion.json"
            published_blob = client.bucket(args.published_bucket).blob(object_name)
            try:
                published_blob.upload_from_string(
                    json.dumps(completion, sort_keys=True, indent=2) + "\n",
                    content_type="application/json", if_generation_match=0,
                )
                published_uri = f"gs://{args.published_bucket}/{object_name}"
            except PreconditionFailed:
                try:
                    existing = json.loads(published_blob.download_as_bytes())
                except Exception as exc:
                    existing = None
                    evaluated["issues"].append(f"existing completion manifest could not be read: {type(exc).__name__}: {exc}")
                if isinstance(existing, dict) and completion_matches(existing, completion):
                    published_uri = f"gs://{args.published_bucket}/{object_name}"
                else:
                    evaluated["complete"] = False
                    evaluated["issues"].append("completion manifest already exists with different contents; refusing to overwrite")
            except Exception as exc:
                try:
                    existing = json.loads(published_blob.download_as_bytes())
                except Exception:
                    existing = None
                if isinstance(existing, dict) and completion_matches(existing, completion):
                    published_uri = f"gs://{args.published_bucket}/{object_name}"
                else:
                    evaluated["complete"] = False
                    evaluated["issues"].append(f"completion manifest upload failed: {type(exc).__name__}: {exc}")
        json_path, html_path = write_reports(args.output_dir, evaluated, published_uri)
        summary = {"run_id": evaluated["run_id"], "complete": evaluated["complete"],
                   "published_manifest_uri": published_uri, "json_report": str(json_path),
                   "html_report": str(html_path), "issues": evaluated["issues"]}
        print(json.dumps(summary, indent=2))
        raise SystemExit(0 if evaluated["complete"] else 2)
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(70)


if __name__ == "__main__":
    main()
