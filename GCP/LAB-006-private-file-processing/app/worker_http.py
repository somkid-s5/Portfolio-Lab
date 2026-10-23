"""Cloud Run worker receiver. Cloud Run IAM is the authentication boundary.
Never expose this application with allUsers Invoker. ce-* is not authentication.
"""
import json
import os
import uuid
from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException
from job_state import Conflict
from storage_events import InvalidEvent, parse_event


def create_app(processor, incoming_bucket, *, metadata_health=None, retry_jobs=None, emit=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 65536
    emit = emit or (lambda record: print(json.dumps(record, sort_keys=True), flush=True))

    @app.before_request
    def identify():
        g.request_id = uuid.uuid4().hex

    @app.after_request
    def finish(response):
        response.headers["X-Request-ID"] = g.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # No request URL, query, headers, payload, signed URL or raw exception.
        record = {"event": "worker_http", "request_id": g.request_id,
                  "status": response.status_code}
        if hasattr(g, "event_id"):
            record.update(event_id=g.event_id, job_id=g.job_id,
                          generation=g.generation)
        emit(record)
        return response

    @app.errorhandler(InvalidEvent)
    def invalid(_):
        return jsonify(error="invalid_storage_event"), 400

    @app.errorhandler(Conflict)
    def retry_conflict(_):
        return jsonify(error="retry_not_allowed"), 409

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error="request_rejected"), exc.code

    @app.errorhandler(Exception)
    def dependency_error(_):
        return jsonify(error="temporary_dependency_failure"), 503

    @app.get("/livez")
    def live():
        return jsonify(alive=True, tier="worker")

    @app.get("/healthz")
    def health():
        if metadata_health is not None:
            metadata_health()
        return jsonify(ready=True, tier="worker")

    @app.post("/events/storage")
    def storage_event():
        event = parse_event(request.headers, request.get_data(cache=False),
                            incoming_bucket)
        if event is None:
            return "", 204
        g.event_id, g.job_id, g.generation = (
            event.event_id, event.job_id, event.generation)
        result = processor.run(event.job_id, event.generation, event.finalized_at)
        if result["status"] == 204:
            return "", 204
        if result["status"] != 503:
            raise RuntimeError("unexpected_processor_status")
        return jsonify(error="retry_event"), 503

    @app.post("/events/retry")
    def retry_event():
        if retry_jobs is None:
            return jsonify(error="retry_unavailable"), 503
        data = request.get_json(silent=True)
        if (not isinstance(data, dict) or set(data) != {"job_id", "epoch"} or
                not isinstance(data["job_id"], str) or
                len(data["job_id"]) != 32 or
                any(c not in "0123456789abcdef" for c in data["job_id"]) or
                type(data["epoch"]) is not int or not 1 <= data["epoch"] <= 2):
            return jsonify(error="invalid_retry_request"), 400
        try:
            job = retry_jobs.read_retry_dispatch(data["job_id"], data["epoch"])
        except KeyError:
            return jsonify(error="job_not_found"), 404
        g.job_id, g.generation = job["job_id"], job["input_generation"]
        g.event_id = "manual-epoch-" + str(data["epoch"])
        result = processor.run(job["job_id"], job["input_generation"],
                               job["input_finalized_at"])
        if result["status"] == 204:
            return "", 204
        return jsonify(error="retry_event"), 503

    return app


def build_app():
    from google.cloud import firestore, storage
    from firestore_jobs import Jobs
    from gcs_objects import Objects
    from processor import Processor

    if (os.environ.get("FIRESTORE_EMULATOR_HOST") or
            os.environ.get("STORAGE_EMULATOR_HOST")):
        raise ValueError("runtime_must_not_use_emulators")
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    database = os.environ["FIRESTORE_DATABASE"]
    if database != "lab006-files":
        raise ValueError("explicit_lab_database_required")
    incoming = os.environ["INCOMING_BUCKET"]
    results = os.environ["RESULTS_BUCKET"]
    fault = os.environ.get("FAIL_AFTER_OUTPUT_ONCE", "false")
    if fault not in ("true", "false"):
        raise ValueError("invalid_fault_configuration")
    client = firestore.Client(project=project, database=database)
    jobs = Jobs(client)
    objects = Objects(storage.Client(project=project), incoming, results)
    processor = Processor(jobs, objects, fail_after_output_once=fault == "true")
    def health():
        client.collection("_health").document("probe").get(timeout=3)
    return create_app(processor, incoming, metadata_health=health, retry_jobs=jobs)
