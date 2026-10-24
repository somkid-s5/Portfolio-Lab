#!/usr/bin/env python3
"""Render a bounded Cloud Batch job JSON file without calling Google Cloud."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


IMAGE_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
REGION_RE = re.compile(r"^[a-z]+-[a-z0-9]+[0-9]$")
JOB_RE = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
EMAIL_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]+\.iam\.gserviceaccount\.com$")


def build_job(args: argparse.Namespace) -> dict:
    if not PROJECT_RE.fullmatch(args.project):
        raise ValueError("project must be a valid lowercase project ID")
    if not REGION_RE.fullmatch(args.region):
        raise ValueError("region must look like asia-southeast1")
    if not IMAGE_RE.fullmatch(args.image_uri):
        raise ValueError("image must be an immutable Artifact Registry URI ending in @sha256:<64 hex>")
    if not EMAIL_RE.fullmatch(args.runtime_service_account):
        raise ValueError("runtime service account email is invalid")
    if not JOB_RE.fullmatch(args.job_id):
        raise ValueError("job id must be lowercase letters, digits, and hyphens")
    common = {
        "allocationPolicy": {
            "location": {"allowedLocations": [f"regions/{args.region}"]},
            "instances": [{"policy": {"machineType": args.machine_type, "provisioningModel": "STANDARD"}}],
            "serviceAccount": {"email": args.runtime_service_account},
            "network": {"networkInterfaces": [{
                "network": f"projects/{args.project}/global/networks/{args.network}",
                "subnetwork": f"projects/{args.project}/regions/{args.region}/subnetworks/{args.subnetwork}",
                "noExternalIpAddress": True,
            }]},
        },
        "logsPolicy": {"destination": "CLOUD_LOGGING"},
        "labels": {"lab": "lab013", "purpose": args.purpose},
    }
    if args.purpose == "process":
        if not args.manifest_uri or not args.attempt_output_bucket:
            raise ValueError("process jobs require --manifest-uri and --attempt-output-bucket")
        if not 1 <= args.task_count <= 64 or not 1 <= args.parallelism <= args.task_count:
            raise ValueError("task count must be 1-64 and parallelism must be 1-task_count")
        if not 60 <= args.timeout_seconds <= 3600:
            raise ValueError("timeout must be bounded between 60 and 3600 seconds")
        environment = {
            "variables": {
                "INPUT_MANIFEST_URI": args.manifest_uri,
                "ATTEMPT_OUTPUT_BUCKET": args.attempt_output_bucket,
            }
        }
        if args.fail_once_index is not None:
            if not 0 <= args.fail_once_index < args.task_count:
                raise ValueError("fail-once index must identify a task")
            environment["variables"]["LAB13_FAIL_ONCE_INDEX"] = str(args.fail_once_index)
        commands = ["-m", "lab13.worker"]
        task_count = args.task_count
        parallelism = args.parallelism
        task_spec = {
            "runnables": [{"displayName": "lab13-worker", "container": {
                "imageUri": args.image_uri, "entrypoint": "python", "commands": commands,
            }}],
            "computeResource": {"cpuMilli": 1000, "memoryMib": 2048},
            "maxRunDuration": f"{args.timeout_seconds}s",
            "maxRetryCount": 1,
            "lifecyclePolicies": [{"action": "RETRY_TASK", "actionCondition": {"exitCodes": [75]}}],
            "environment": environment,
        }
    else:
        if args.purpose != "iam-probe" or not args.input_bucket or not args.published_bucket or not args.probe_id:
            raise ValueError("iam-probe jobs require --input-bucket, --published-bucket, and --probe-id")
        if args.input_bucket == args.published_bucket:
            raise ValueError("input and published buckets must be different")
        commands = ["-m", "lab13.iam_probe", "--input-bucket", args.input_bucket,
                    "--published-bucket", args.published_bucket, "--probe-id", args.probe_id]
        task_count = 1
        parallelism = 1
        task_spec = {
            "runnables": [{"displayName": "lab13-runtime-iam-probe", "container": {
                "imageUri": args.image_uri, "entrypoint": "python", "commands": commands,
            }}],
            "computeResource": {"cpuMilli": 1000, "memoryMib": 2048},
            "maxRunDuration": "300s",
            "maxRetryCount": 0,
        }
    common["taskGroups"] = [{
        "taskCount": task_count,
        "parallelism": parallelism,
        "taskCountPerNode": 1,
        "taskSpec": task_spec,
    }]
    return common


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purpose", choices=("process", "iam-probe"), required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="asia-southeast1")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--image-uri", required=True)
    parser.add_argument("--runtime-service-account", required=True)
    parser.add_argument("--network", default="lab013-vpc")
    parser.add_argument("--subnetwork", default="lab013-workers")
    parser.add_argument("--machine-type", default="e2-standard-2")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--manifest-uri")
    parser.add_argument("--attempt-output-bucket")
    parser.add_argument("--task-count", type=int, default=8)
    parser.add_argument("--parallelism", type=int, default=2)
    parser.add_argument("--fail-once-index", type=int)
    parser.add_argument("--input-bucket")
    parser.add_argument("--published-bucket")
    parser.add_argument("--probe-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 60 <= args.timeout_seconds <= 3600:
        parser.error("timeout-seconds must be from 60 through 3600")
    try:
        config = build_job(args)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"job_id": args.job_id, "config": str(args.output),
                      "task_count": config["taskGroups"][0]["taskCount"],
                      "parallelism": config["taskGroups"][0]["parallelism"],
                      "no_external_ip": config["allocationPolicy"]["network"]["networkInterfaces"][0]["noExternalIpAddress"],
                      "image_uri": args.image_uri}, indent=2))


if __name__ == "__main__":
    main()
