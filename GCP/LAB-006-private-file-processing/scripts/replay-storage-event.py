"""Bounded authenticated replay of an existing sandbox Storage finalize event.
Never prints tokens or signed URLs. A 204 is acknowledgement, not business PASS.
"""
import argparse
import json
import re
import subprocess
import sys
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class ReplayError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def configuration(project, bucket, job_id, generation, origin, service_account):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
        raise ReplayError("invalid_project")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]", bucket):
        raise ReplayError("invalid_bucket")
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ReplayError("invalid_job")
    if not re.fullmatch(r"[1-9][0-9]{0,29}", generation):
        raise ReplayError("invalid_generation")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or
            not parsed.hostname.endswith(".run.app") or
            parsed.netloc != parsed.hostname or
            parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ReplayError("invalid_worker_origin")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]@"+
                        re.escape(project)+r"\.iam\.gserviceaccount\.com",
                        service_account):
        raise ReplayError("invalid_service_account")
    return origin.rstrip("/")


def event_payload(client, project, bucket, job_id, generation):
    name = f"incoming/{job_id}/source.csv"
    blob = client.bucket(bucket).blob(name, generation=int(generation))
    blob.reload(if_generation_match=int(generation), timeout=5, retry=None)
    if (str(blob.generation) != generation or blob.name != name or
            blob.bucket.name != bucket or blob.time_created is None):
        raise ReplayError("source_binding_mismatch")
    created = blob.time_created
    if created.tzinfo is None or created.utcoffset().total_seconds() != 0:
        raise ReplayError("invalid_storage_time")
    body = json.dumps({"bucket": bucket, "name": name, "generation": generation,
                       "timeCreated": created.isoformat().replace("+00:00", "Z")},
                      separators=(",", ":")).encode()
    if len(body) > 4096:
        raise ReplayError("event_too_large")
    source = f"//storage.googleapis.com/projects/_/buckets/{bucket}"
    return body, source, "objects/"+name


def identity_token(origin, service_account):
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-identity-token",
             "--impersonate-service-account="+service_account,
             "--audiences="+origin, "--quiet"],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ReplayError("identity_token_unavailable") from None
    token = result.stdout.strip()
    if result.returncode or not re.fullmatch(
            r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
        raise ReplayError("identity_token_unavailable")
    return token


def replay(opener, origin, token, body, source, subject):
    event_id = "lab006-replay-"+uuid.uuid4().hex
    ids = [event_id, event_id, "lab006-replay-"+uuid.uuid4().hex]
    outcomes = []
    for event in ids:
        request = Request(origin+"/events/storage", data=body, method="POST",
                          headers={"Authorization": "Bearer "+token,
                                   "Content-Type": "application/json",
                                   "Ce-Specversion": "1.0",
                                   "Ce-Type": "google.cloud.storage.object.v1.finalized",
                                   "Ce-Id": event, "Ce-Source": source,
                                   "Ce-Subject": subject})
        try:
            with opener.open(request, timeout=10) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
            error.close()
        except OSError:
            outcomes.append({"event_id": event, "outcome": "unknown"})
            break  # A lost reply is not permission to send unbounded extra requests.
        outcomes.append({"event_id": event, "http_status": status})
        if status != 204:
            break
    return outcomes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "bucket", "job-id", "generation", "worker-origin",
                 "service-account"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--confirm-sandbox", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.confirm_sandbox:
            raise ReplayError("sandbox_confirmation_required")
        origin = configuration(args.project, args.bucket, args.job_id,
                               args.generation, args.worker_origin,
                               args.service_account)
        from google.cloud import storage
        client = storage.Client(project=args.project)
        body, source, subject = event_payload(client, args.project, args.bucket,
                                             args.job_id, args.generation)
        token = identity_token(origin, args.service_account)
        outcomes = replay(build_opener(ProxyHandler({}), NoRedirect()),
                          origin, token, body, source, subject)
        print(json.dumps({"job_id": args.job_id, "generation": args.generation,
                          "requests": outcomes,
                          "business_verification": "required_separately"}))
        return 0 if len(outcomes) == 3 and all(
            o.get("http_status") == 204 for o in outcomes) else 1
    except ReplayError as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except Exception:
        print(json.dumps({"error": "replay_unresolved_check_source_identity_and_logs"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
