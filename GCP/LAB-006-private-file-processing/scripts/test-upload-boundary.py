"""Bounded signed POST boundary observation. One logical job per private journal.
Results are observations, not PASS claims; inspect policies and object absence too.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener
from portal_client import Client, NoRedirect, origin, read_logins

SOURCE = (b"sale_id,sku,quantity,unit_price_satang\n"
          b"S1,BOOK-01,2,12500\nS2,USB-01,1,9900\nS3,BOOK-01,3,12500\n")


def private_read(path):
    # The same regular-file/permissions/size gate as private demo logins.
    return read_logins(path)


def save(path, value, *, new=False):
    path = Path(path)
    if new:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        return
    # Only replaces this tool's validated private journal, never an arbitrary tree.
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def multipart(policy, job_id, bucket, case):
    if case not in ("positive", "oversize", "mime"):
        raise ValueError("invalid_case")
    target = urlsplit(policy["url"])
    if (target.scheme != "https" or target.hostname != "storage.googleapis.com" or
            target.port not in (None, 443) or target.username or target.password or
            target.query or target.fragment or target.path.rstrip("/") != "/"+bucket):
        raise ValueError("unexpected_storage_endpoint")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
        raise ValueError("invalid_bucket")
    fields = dict(policy["fields"])
    if (len(fields) > 20 or
            any(not isinstance(k, str) or not isinstance(v, str) or
                len(k) > 100 or len(v) > 20000 or "\r" in k or "\n" in k or '"' in k
                for k, v in fields.items()) or
            fields.get("key") != f"incoming/{job_id}/source.csv" or
            fields.get("Content-Type") != "text/csv"):
        raise ValueError("unexpected_policy_fields")
    decoded = json.loads(base64.b64decode(fields["policy"], validate=True))
    ranges = [c for c in decoded["conditions"] if isinstance(c, list) and
              len(c) == 3 and c[0] == "content-length-range"]
    if (len(ranges) != 1 or ranges[0][1] != 1 or
            type(ranges[0][2]) is not int or not 1 <= ranges[0][2] <= 5242880):
        raise ValueError("unexpected_policy_size_bound")
    for exact in ({"bucket": bucket}, {"key": fields["key"]}, {"Content-Type": "text/csv"}):
        if exact not in decoded["conditions"]:
            raise ValueError("missing_exact_policy_condition")
    maximum = ranges[0][2]
    payload = SOURCE if case != "oversize" else b"x"*(maximum+1)
    mime = "application/octet-stream" if case == "mime" else "text/csv"
    if case == "mime":
        fields["Content-Type"] = mime
    boundary = "Lab006-" + secrets.token_hex(16)
    chunks = []
    for key, value in fields.items():
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
                       f'\r\n\r\n{value}\r\n').encode())
    chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                   f'filename="source.csv"\r\nContent-Type: {mime}\r\n\r\n').encode())
    chunks.extend([payload, f"\r\n--{boundary}--\r\n".encode()])
    return Request(policy["url"], data=b"".join(chunks), method="POST",
                   headers={"Content-Type": "multipart/form-data; boundary="+boundary})


def send(request, *, opener=None):
    opener = opener or build_opener(ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=15)
    except HTTPError as exc:
        response = exc
    with response:
        status = response.code
        body = response.read(65537)
    if len(body) > 65536:
        raise ValueError("storage_reply_too_large")
    code = re.search(rb"<Code>([A-Za-z][A-Za-z0-9_]{0,63})</Code>", body)
    return {"storage_http": status,
            "storage_error_code": code.group(1).decode() if code else None}


def run(base_url, logins_file, journal, bucket, case):
    base_url = origin(base_url)
    if case not in ("positive", "oversize", "mime") or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
        raise ValueError("invalid_boundary_contract")
    path = Path(journal)
    if not path.parent.is_dir() or path.parent.stat().st_mode & 0o077:
        raise ValueError("private_journal_parent_required")
    binding = {"origin": base_url, "bucket": bucket, "case": case, "owner": "alice"}
    if path.exists() or path.is_symlink():
        record = private_read(path)
        if any(record.get(key) != value for key, value in binding.items()):
            raise ValueError("journal_binding_mismatch")
        if "result" in record:
            return {"event": "stored_result_not_retest", **record["result"]}
    else:
        record = {**binding, "key": "boundary-"+uuid.uuid4().hex}
        save(path, record, new=True)
    credentials = read_logins(logins_file)["alice"]
    client = Client(base_url)
    client.login("alice", credentials["password"])
    if "job_id" not in record:
        status, value = client.call("/api/jobs",
                                    data={"display_name": "boundary-"+case+".csv"},
                                    key=record["key"])
        if status not in (200, 201) or not re.fullmatch(r"[a-f0-9]{32}", value.get("job_id", "")):
            raise ValueError("job_creation_unresolved")
        record["job_id"] = value["job_id"]
        save(path, record)
    status, job = client.call("/api/jobs/"+record["job_id"])
    if status != 200 or job["state"] != "awaiting_upload":
        raise ValueError("inspect_existing_job_before_resending")
    status, policy = client.call("/api/jobs/"+record["job_id"]+"/upload-policy", data={})
    if status != 200:
        raise ValueError("policy_unavailable")
    observed = send(multipart(policy, record["job_id"], bucket, case))
    result = {"job_id": record["job_id"], "case": case, **observed,
              "interpretation": "Observed HTTP only; verify positive control, policy reason and object absence."}
    record["result"] = result
    save(path, record)
    return {"event": "boundary_observation", **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--logins-file", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--case", choices=["positive", "oversize", "mime"], required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.base_url, args.logins_file, args.journal,
                             args.bucket, args.case), sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"event": "boundary_unresolved", "error_type": type(exc).__name__,
                          "action": "Keep the same journal; inspect the existing job before retry."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
