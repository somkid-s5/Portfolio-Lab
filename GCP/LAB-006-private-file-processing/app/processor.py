"""Worker orchestration. Caller validates CloudEvent envelope and Cloud Run IAM.
Storage adapter must pin source generation, bound reads and create-or-verify output.
No raw exception, file bytes, URLs or credentials are returned to HTTP callers.
"""
import hashlib
import uuid
from csv_domain import Rejected, canonical_bytes, summarize
from job_state import Conflict


class IntegrityFailure(Exception):
    pass


class Processor:
    def __init__(self, jobs, objects, *, fail_after_output_once=False):
        self.jobs = jobs
        self.objects = objects
        self.fail_after_output_once = fail_after_output_once

    def run(self, job_id, generation, finalized_at):
        token = uuid.uuid4().hex
        try:
            claimed = self.jobs.claim(job_id, generation, token,
                                      finalized_at=finalized_at)
        except KeyError:
            return {"status": 204, "reason": "unknown_job"}
        disposition = claimed["disposition"]
        if disposition == "busy":
            return {"status": 503, "reason": "lease_busy"}
        if disposition != "claimed":
            return {"status": 204, "reason": disposition}
        job = claimed["job"]
        try:
            data = self.objects.read_source(job["object_name"], generation,
                                            job["max_bytes"])
            summary = summarize(data, max_bytes=job["max_bytes"],
                                max_rows=job["max_rows"],
                                processor_version=job["processor_version"])
            body = canonical_bytes(summary)
            name = (f"results/{job_id}/{generation}/"
                    f"{job['processor_version']}/summary.json")
            output_generation = self.objects.create_or_verify(
                name, body, input_sha256=summary["input_sha256"],
                processor_version=job["processor_version"])
            binding = {"name": name, "generation": output_generation,
                       "sha256": hashlib.sha256(body).hexdigest(),
                       "input_sha256": summary["input_sha256"]}
            if (self.fail_after_output_once and
                    self.jobs.consume_output_fault(job_id, token)):
                # Marker is durable before the deliberate gap; output is already written.
                self.jobs.release_transient(job_id, token)
                return {"status": 503, "reason": "intentional_after_output"}
            self.jobs.finish(job_id, token, output=binding)
            return {"status": 204, "reason": "succeeded"}
        except Rejected as exc:
            try:
                self.jobs.finish(job_id, token, reason=exc.code)
            except Conflict:
                return {"status": 503, "reason": "stale_attempt"}
            return {"status": 204, "reason": "rejected"}
        except IntegrityFailure:
            try:
                self.jobs.finish(job_id, token, reason="failed_integrity")
            except Conflict:
                return {"status": 503, "reason": "stale_attempt"}
            return {"status": 204, "reason": "failed_integrity"}
        except Conflict:
            return {"status": 503, "reason": "stale_attempt"}
        except Exception:
            # Database failure can prevent release; bounded lease still permits recovery.
            try:
                self.jobs.release_transient(job_id, token)
            except Exception:
                pass
            return {"status": 503, "reason": "transient_dependency"}
