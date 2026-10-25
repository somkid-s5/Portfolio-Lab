"""Cloud Run Job command entrypoint for Daily Sales Close."""
import argparse
from datetime import datetime, timezone
import json
import os
import sys

import google.auth
from google.cloud import firestore, pubsub_v1, storage

from app.integrations import ReportReadyPublisher
from app.ledger import FirestoreLedger
from app.storage import GCSObjects
from app.worker import DailyReportWorker, WorkerFailure


def _required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("missing_runtime_configuration")
    return value


def _emit(event):
    sys.stdout.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _parser():
    parser = argparse.ArgumentParser(description="Build one bounded daily synthetic sales report.")
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--mode", choices=("scheduled", "operator-backfill"),
                        default="scheduled")
    parser.add_argument("--source-object")
    parser.add_argument("--source-generation")
    return parser


def _worker_from_env():
    project = _required("GOOGLE_CLOUD_PROJECT")
    credentials, discovered_project = google.auth.default()
    if discovered_project and discovered_project != project:
        raise RuntimeError("runtime_project_mismatch")
    database = _required("FIRESTORE_DATABASE")
    collection = os.environ.get("FIRESTORE_COLLECTION", "daily_runs").strip()
    source_bucket = _required("SOURCE_BUCKET")
    report_bucket = _required("REPORT_BUCKET")
    topic = _required("REPORT_READY_TOPIC")

    ledger_client = firestore.Client(
        project=project, database=database, credentials=credentials)
    storage_client = storage.Client(project=project, credentials=credentials)
    publisher_client = pubsub_v1.PublisherClient()
    return DailyReportWorker(
        ledger=FirestoreLedger(ledger_client, collection=collection),
        objects=GCSObjects(storage_client, source_bucket, report_bucket),
        publisher=ReportReadyPublisher(publisher_client, topic=topic),
    )


def main(argv=None):
    args = _parser().parse_args(argv)
    execution = os.environ.get("CLOUD_RUN_EXECUTION", "").strip()
    attempt_text = os.environ.get("CLOUD_RUN_TASK_ATTEMPT", "0").strip()
    if not execution or not attempt_text.isdigit():
        _emit({"event": "daily_report_run_failed",
               "business_date": args.business_date,
               "reason": "invalid_execution_metadata"})
        return 2
    try:
        task_attempt = int(attempt_text)
        worker = _worker_from_env()
        result = worker.run(
            business_date=args.business_date,
            execution=execution,
            task_attempt=task_attempt,
            mode=args.mode,
            source_object=args.source_object,
            source_generation=args.source_generation,
        )
    except WorkerFailure as exc:
        _emit({"event": "daily_report_run_failed",
               "business_date": args.business_date,
               "reason": exc.code})
        return 1
    except Exception as exc:
        _emit({"event": "daily_report_run_failed",
               "business_date": args.business_date,
               "reason": "worker_configuration_or_dependency_failure",
               "failure_class": type(exc).__name__})
        return 1
    _emit({
        "event": "daily_report_run_finished",
        "business_date": result["business_date"],
        "status": result["status"],
        "report_id": result.get("report_id"),
        "report_generation": result.get("report_generation"),
    })
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
