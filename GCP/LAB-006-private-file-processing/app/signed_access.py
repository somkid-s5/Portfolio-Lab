"""Issue short-lived bearer capabilities only after server-side owner checks.
Token supplier uses attached runtime credentials; no service-account key file.
"""
from datetime import datetime, timedelta, timezone
import re
from job_state import Conflict


class Access:
    def __init__(self, jobs, storage_client, incoming_bucket, results_bucket,
                 upload_signer, download_signer, token_supplier, *, clock=None):
        if incoming_bucket == results_bucket:
            raise ValueError("separate_buckets_required")
        for signer in (upload_signer, download_signer):
            if not re.fullmatch(r"[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com", signer):
                raise ValueError("invalid_signer")
        self.jobs, self.client = jobs, storage_client
        self.incoming, self.results = incoming_bucket, results_bucket
        self.upload_signer, self.download_signer = upload_signer, download_signer
        self.token_supplier = token_supplier
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _owned(self, job_id, owner):
        job = self.jobs.read_owned(job_id, owner)
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("utc_time_required")
        if now >= job["expires_at"]:
            raise Conflict("job_expired")
        return job, now

    def upload_policy(self, job_id, owner):
        job, now = self._owned(job_id, owner)
        deadline = min(job["upload_deadline"], job["expires_at"],
                       now + timedelta(seconds=300))
        if (job["state"] != "awaiting_upload" or job["input_generation"] is not None or
                (deadline - now).total_seconds() < 1):
            raise Conflict("upload_not_allowed")
        if job["object_name"] != f"incoming/{job_id}/source.csv":
            raise Conflict("invalid_object_binding")
        policy = self.client.generate_signed_post_policy_v4(
            self.incoming, job["object_name"], expiration=deadline,
            conditions=[["content-length-range", 1, job["max_bytes"]]],
            fields={"Content-Type": "text/csv", "success_action_status": "201"},
            service_account_email=self.upload_signer,
            access_token=self.token_supplier())
        return {"url": policy["url"], "fields": policy["fields"],
                "expires_at": deadline.isoformat(), "max_bytes": job["max_bytes"]}

    def download_link(self, job_id, owner):
        job, now = self._owned(job_id, owner)
        if job["state"] != "succeeded":
            raise Conflict("result_not_ready")
        remaining = int((job["expires_at"] - now).total_seconds())
        ttl = min(60, remaining)
        if ttl < 1:
            raise Conflict("job_expired")
        expected = (f"results/{job_id}/{job['input_generation']}/"
                    f"{job['processor_version']}/summary.json")
        if job["output_name"] != expected:
            raise Conflict("invalid_output_binding")
        generation = job["output_generation"]
        if not re.fullmatch(r"[1-9][0-9]{0,29}", generation):
            raise Conflict("invalid_output_binding")
        deadline = now + timedelta(seconds=ttl)
        blob = self.client.bucket(self.results).blob(expected, generation=int(generation))
        url = blob.generate_signed_url(
            version="v4", expiration=deadline, method="GET",
            generation=generation, service_account_email=self.download_signer,
            access_token=self.token_supplier(),
            response_disposition='attachment; filename="summary.json"',
            response_type="application/json")
        return {"url": url, "expires_at": deadline.isoformat()}
