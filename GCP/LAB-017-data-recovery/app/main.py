from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import psycopg
from google.api_core.exceptions import GoogleAPICallError, NotFound, PreconditionFailed
from google.cloud import storage

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
RECORD_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
ALLOWED_STATUS = {"NEW", "REVIEW", "APPROVED", "REJECTED"}
MAX_BODY = 32768
MAX_ATTACHMENT = 16384


class ObjectMissing(Exception):
    pass


class ObjectConflict(Exception):
    pass


class MemoryStorage:
    """In-memory object store used only by the repository integration tests."""
    def __init__(self):
        self.live = {}
        self.deleted = {}
        self.counter = 100

    def reset(self):
        self.live.clear()
        self.deleted.clear()
        self.counter = 100

    def put_if_absent(self, key: str, content: bytes, content_type: str, checksum: str) -> int:
        current = self.live.get(key)
        if current:
            if hashlib.sha256(current[0]).hexdigest() != checksum:
                raise ObjectConflict("object key already contains different bytes")
            return current[2]
        self.counter += 1
        self.live[key] = (content, content_type, self.counter)
        return self.counter

    def get(self, key: str) -> tuple[bytes, int]:
        current = self.live.get(key)
        if not current:
            raise ObjectMissing(key)
        return current[0], current[2]

    def delete_live(self, key: str) -> int:
        current = self.live.pop(key)
        self.deleted.setdefault(key, []).append(current)
        return current[2]

    def restore_deleted(self, key: str, generation: int) -> int:
        versions = self.deleted.get(key, [])
        old = next((item for item in versions if item[2] == generation), None)
        if old is None:
            raise ObjectMissing(key)
        self.counter += 1
        self.live[key] = (old[0], old[1], self.counter)
        return self.counter


MEMORY_STORE = MemoryStorage()
_GCS_STORE = None


class GCSStorage:
    def __init__(self):
        bucket_name = os.environ["STORAGE_BUCKET"]
        self.bucket = storage.Client().bucket(bucket_name)

    def put_if_absent(self, key: str, content: bytes, content_type: str, checksum: str) -> int:
        blob = self.bucket.blob(key)
        blob.metadata = {"sha256": checksum}
        try:
            blob.upload_from_string(content, content_type=content_type, if_generation_match=0)
        except PreconditionFailed:
            existing = self.bucket.get_blob(key)
            if existing is None:
                raise ObjectMissing(key)
            existing_bytes = existing.download_as_bytes()
            if hashlib.sha256(existing_bytes).hexdigest() != checksum:
                raise ObjectConflict("object key already contains different bytes")
            return int(existing.generation)
        return int(blob.generation)

    def get(self, key: str) -> tuple[bytes, int]:
        blob = self.bucket.get_blob(key)
        if blob is None:
            raise ObjectMissing(key)
        return blob.download_as_bytes(), int(blob.generation)


def get_storage():
    global _GCS_STORE
    if os.getenv("STORAGE_BACKEND") == "memory":
        return MEMORY_STORE
    if _GCS_STORE is None:
        _GCS_STORE = GCSStorage()
    return _GCS_STORE


def connect_db():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "records"),
        user=os.getenv("DB_USER", "records_app"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=5,
        application_name="lab017-records-api",
    )


def now_text(value) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def query_manifest(conn, drill_id: str) -> dict:
    rows = conn.execute(
        """SELECT id, record_ref, title, status, amount_cents, state,
                  attachment_key, attachment_sha256, attachment_bytes, created_at
             FROM public.records
            WHERE drill_id = %s
            ORDER BY record_ref""",
        (drill_id,),
    ).fetchall()
    total = sum(row[4] for row in rows)
    sequence_last_value, sequence_is_called = conn.execute(
        "SELECT last_value, is_called FROM public.records_id_seq"
    ).fetchone()
    by_status = {}
    checks = []
    records = []
    store = get_storage()
    for row in rows:
        state_ok = row[5] == "READY"
        object_ok = False
        generation = None
        if state_ok:
            try:
                content, generation = store.get(row[6])
                object_ok = (
                    hashlib.sha256(content).hexdigest() == row[7]
                    and len(content) == row[8]
                )
            except ObjectMissing:
                object_ok = False
        checks.append(state_ok and object_ok)
        by_status[row[3]] = by_status.get(row[3], 0) + 1
        records.append({
            "id": row[0],
            "record_ref": row[1],
            "title": row[2],
            "status": row[3],
            "amount_cents": row[4],
            "state": row[5],
            "attachment_key": row[6],
            "attachment_sha256": row[7],
            "attachment_bytes": row[8],
            "attachment_generation": generation,
            "created_at": now_text(row[9]),
        })
    return {
        "drill_id": drill_id,
        "database": {
            "count": len(rows),
            "total_amount_cents": total,
            "max_id": max((row[0] for row in rows), default=0),
            "sequence_last_value": sequence_last_value,
            "sequence_is_called": sequence_is_called,
            "by_status": dict(sorted(by_status.items())),
            "records": records,
        },
        "objects_ok": all(checks),
        "integrity_pass": all(checks) and all(row[5] == "READY" for row in rows),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "RecordsLab/1.0"

    def _send(self, status: int, payload: dict, content_type: str = "application/json; charset=utf-8") -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _maintenance(self, path: str) -> bool:
        if os.getenv("MAINTENANCE_MODE", "false").strip().lower() not in {"1", "true", "yes"}:
            return False
        if path in {"/healthz", "/readyz", "/ops/manifest"}:
            return False
        self._send(503, {"error": "maintenance_mode", "message": "Recovery is in progress; retry after the validation gate."})
        return True

    def _path(self) -> str:
        return urlsplit(self.path).path

    def _read_json(self) -> dict:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("invalid_content_length")
        if length < 1 or length > MAX_BODY:
            raise ValueError("request_body_out_of_range")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("json_object_required")
        return value

    def log_message(self, fmt: str, *args) -> None:
        logging.info(json.dumps({
            "event": "http_access",
            "method": self.command,
            "path": self._path(),
            "message": fmt % args,
        }, ensure_ascii=False))

    def do_GET(self) -> None:
        path = self._path()
        if path == "/healthz":
            self._send(200, {"status": "ok"})
            return
        if self._maintenance(path):
            return
        try:
            if path == "/readyz":
                with connect_db() as conn:
                    conn.execute("SELECT 1").fetchone()
                if not os.getenv("STORAGE_BUCKET"):
                    raise ValueError("storage_not_configured")
                self._send(200, {"status": "ready"})
                return
            if path == "/v1/records":
                query = parse_qs(urlsplit(self.path).query)
                drill_id = query.get("drill_id", [""])[0]
                if not RECORD_REF.fullmatch(drill_id):
                    self._send(400, {"error": "invalid_drill_id"})
                    return
                with connect_db() as conn:
                    result = query_manifest(conn, drill_id)
                self._send(200, result)
                return
            if path == "/ops/manifest":
                query = parse_qs(urlsplit(self.path).query)
                drill_id = query.get("drill_id", [""])[0]
                if not RECORD_REF.fullmatch(drill_id):
                    self._send(400, {"error": "invalid_drill_id"})
                    return
                with connect_db() as conn:
                    result = query_manifest(conn, drill_id)
                self._send(200, result)
                return
            match = re.fullmatch(r"/v1/records/([A-Za-z0-9][A-Za-z0-9._-]{0,63})(/attachment)?", path)
            if match:
                record_ref, attachment_route = match.groups()
                with connect_db() as conn:
                    row = conn.execute(
                        """SELECT record_ref, title, status, amount_cents, state,
                                  attachment_key, attachment_sha256, attachment_bytes
                             FROM public.records WHERE record_ref = %s""",
                        (record_ref,),
                    ).fetchone()
                if row is None or row[4] != "READY":
                    self._send(404, {"error": "record_not_found"})
                    return
                if attachment_route:
                    content, _generation = get_storage().get(row[5])
                    if hashlib.sha256(content).hexdigest() != row[6] or len(content) != row[7]:
                        self._send(409, {"error": "attachment_integrity_failed"})
                        return
                    self._send(200, {"content_utf8": content.decode("utf-8")})
                    return
                self._send(200, {
                    "record_ref": row[0], "title": row[1], "status": row[2],
                    "amount_cents": row[3], "attachment_key": row[5],
                    "attachment_sha256": row[6], "attachment_bytes": row[7],
                })
                return
            self._send(404, {"error": "not_found"})
        except ObjectMissing:
            self._send(404, {"error": "attachment_not_found"})
        except (psycopg.Error, OSError, GoogleAPICallError):
            logging.exception(json.dumps({"event": "read_failed", "path": path}))
            self._send(503, {"error": "dependency_unavailable"})
        except ValueError as exc:
            if str(exc) == "storage_not_configured":
                self._send(503, {"error": "storage_not_configured"})
            else:
                self._send(400, {"error": "invalid_request"})

    def do_DELETE(self) -> None:
        self._send(405, {"error": "method_not_allowed"})

    def do_POST(self) -> None:
        path = self._path()
        if self._maintenance(path):
            return
        if path != "/v1/records":
            self._send(404, {"error": "not_found"})
            return
        try:
            payload = self._read_json()
            record_ref = payload.get("record_ref")
            drill_id = payload.get("drill_id")
            title = payload.get("title")
            status = payload.get("status", "NEW")
            amount = payload.get("amount_cents")
            filename = payload.get("attachment_name")
            text = payload.get("attachment_text")
            if not isinstance(record_ref, str) or not RECORD_REF.fullmatch(record_ref):
                raise ValueError("invalid_record_ref")
            if not isinstance(drill_id, str) or not RECORD_REF.fullmatch(drill_id):
                raise ValueError("invalid_drill_id")
            if not isinstance(title, str) or not title.strip() or len(title) > 120:
                raise ValueError("invalid_title")
            if not isinstance(status, str) or status not in ALLOWED_STATUS:
                raise ValueError("invalid_status")
            if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0 or amount > 100000000:
                raise ValueError("invalid_amount")
            if not isinstance(filename, str) or not FILENAME.fullmatch(filename):
                raise ValueError("invalid_attachment_name")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("invalid_attachment_text")
            content = text.encode("utf-8")
            if len(content) > MAX_ATTACHMENT:
                raise ValueError("attachment_too_large")
            checksum = hashlib.sha256(content).hexdigest()
            key = f"records/{drill_id}/{record_ref}/{filename}"
            with connect_db() as conn:
                inserted = conn.execute(
                    """INSERT INTO public.records
                           (record_ref, drill_id, title, status, amount_cents,
                            attachment_key, attachment_sha256, attachment_bytes, state)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING')
                       ON CONFLICT (record_ref) DO NOTHING
                       RETURNING id""",
                    (record_ref, drill_id, title.strip(), status, amount, key, checksum, len(content)),
                ).fetchone()
                if inserted is None:
                    existing = conn.execute(
                        """SELECT id, drill_id, title, status, amount_cents,
                                  attachment_key, attachment_sha256, attachment_bytes, state
                             FROM public.records WHERE record_ref = %s""",
                        (record_ref,),
                    ).fetchone()
                    expected = (drill_id, title.strip(), status, amount, key, checksum, len(content))
                    actual = tuple(existing[1:8]) if existing else None
                    if actual != expected:
                        self._send(409, {"error": "record_ref_conflict"})
                        return
                    record_id = existing[0]
                    already_ready = existing[8] == "READY"
                else:
                    record_id = inserted[0]
                    already_ready = False
            if not already_ready:
                get_storage().put_if_absent(key, content, "text/plain; charset=utf-8", checksum)
                with connect_db() as conn:
                    conn.execute(
                        """UPDATE public.records SET state='READY', updated_at=clock_timestamp()
                             WHERE record_ref=%s AND attachment_sha256=%s AND state='PENDING'""",
                        (record_ref, checksum),
                    )
            self._send(200 if already_ready else 201, {
                "record_id": record_id, "record_ref": record_ref, "state": "READY",
                "attachment_key": key, "attachment_sha256": checksum,
            })
        except ValueError:
            self._send(400, {"error": "invalid_request"})
        except ObjectConflict:
            self._send(409, {"error": "attachment_key_conflict"})
        except (psycopg.Error, OSError, GoogleAPICallError):
            logging.exception(json.dumps({"event": "create_failed"}))
            self._send(503, {"error": "dependency_unavailable"})


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), Handler)
    logging.info(json.dumps({"event": "server_started", "port": int(os.getenv("PORT", "8080"))}))
    server.serve_forever()


if __name__ == "__main__":
    main()
