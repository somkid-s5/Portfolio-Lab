"""Environment-backed client factory for the private coordinator service."""
import os

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore, storage

from app.coordinator import CoordinatorDependencies, create_app
from app.integrations import CloudRunJobRunner
from app.ledger import FirestoreLedger
from app.storage import GCSObjects


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("missing_runtime_configuration")
    return value


def create_app_from_env():
    project = _required("GOOGLE_CLOUD_PROJECT")
    credentials, discovered_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if discovered_project and discovered_project != project:
        raise RuntimeError("runtime_project_mismatch")

    region = _required("RUN_REGION")
    job_name = _required("RUN_JOB_NAME")
    report_job = _required("REPORT_SCHEDULER_JOB_NAME")
    watchdog_job = _required("WATCHDOG_SCHEDULER_JOB_NAME")
    firestore_database = _required("FIRESTORE_DATABASE")
    collection = os.environ.get("FIRESTORE_COLLECTION", "daily_runs").strip()
    source_bucket = _required("SOURCE_BUCKET")
    report_bucket = _required("REPORT_BUCKET")

    ledger_client = firestore.Client(
        project=project, database=firestore_database, credentials=credentials)
    storage_client = storage.Client(project=project, credentials=credentials)
    ledger = FirestoreLedger(ledger_client, collection=collection)
    objects = GCSObjects(storage_client, source_bucket, report_bucket)
    runner = CloudRunJobRunner(
        AuthorizedSession(credentials), project=project, region=region, job=job_name)
    return create_app(CoordinatorDependencies(
        runner=runner,
        ledger=ledger,
        objects=objects,
        report_job_name=report_job,
        watchdog_job_name=watchdog_job,
    ))
