import base64
from contextlib import redirect_stdout
import io
import json
import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/lab20-global-test.db")
os.environ.setdefault("APP_LOCAL_TEST", "1")

from flask import request
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.api import create_app
from app.database_schema import apply_schema
from app.worker import create_app as create_worker_app


class Future:
    def result(self, timeout=None):
        return "message-1"


class FakePublisher:
    def __init__(self):
        self.events = []

    def publish(self, topic, data):
        self.events.append((topic, data))
        return Future()


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket = bucket
        self.name = name

    def upload_from_string(self, data, **kwargs):
        self.bucket.objects[self.name] = data.encode() if isinstance(data, str) else data

    def download_as_bytes(self):
        return self.bucket.objects[self.name]

    def reload(self):
        return None


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def blob(self, name):
        return FakeBlob(self, name)


class FakeStorage:
    def __init__(self):
        self.buckets = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, FakeBucket())


class Lab020ApplicationTests(unittest.TestCase):
    def setUp(self):
        url = os.getenv("TEST_DATABASE_URL")
        if url:
            self.engine = create_engine(url, pool_pre_ping=True)
        else:
            self.engine = create_engine(
                "sqlite+pysqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        apply_schema(self.engine, seed=True)
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM report_jobs"))
            connection.execute(text("DELETE FROM bookings"))
            connection.execute(text("UPDATE slots SET booked=0"))
        self.publisher = FakePublisher()
        self.storage = FakeStorage()
        self.api = create_app(
            engine=self.engine,
            publisher=self.publisher,
            storage=self.storage,
            identity_resolver=lambda: request.headers.get("X-Test-User"),
        ).test_client()
        self.worker = create_worker_app(engine=self.engine, storage=self.storage).test_client()

    def tearDown(self):
        self.engine.dispose()

    def booking(self, user, key, slot="consult-morning"):
        return self.api.post(
            "/api/bookings",
            json={"slot_id": slot},
            headers={"X-Test-User": user, "Idempotency-Key": key},
        )

    def test_migrations_are_tracked_and_safe_to_repeat(self):
        apply_schema(self.engine, seed=True)
        with self.engine.connect() as connection:
            versions = connection.execute(
                text("SELECT version FROM schema_migrations ORDER BY version")
            ).scalars().all()
            slots = connection.execute(text("SELECT COUNT(*) FROM slots")).scalar_one()
        self.assertEqual(versions, ["001_initial"])
        self.assertEqual(slots, 3)

    def test_request_logs_hash_identity_instead_of_email(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.booking("private.person@example.test", "booking-key-0009")
        self.assertEqual(result.status_code, 201)
        self.assertIn('"actor_hash":', output.getvalue())
        self.assertNotIn("private.person@example.test", output.getvalue())

    def test_postgres_runtime_roles_have_separate_table_privileges(self):
        if self.engine.dialect.name != "postgresql":
            self.skipTest("PostgreSQL grants are checked only against the disposable CI PostgreSQL service")
        roles = ("lab20ci_api_role", "lab20ci_api_user", "lab20ci_worker_role", "lab20ci_worker_user")
        with self.engine.begin() as connection:
            for role in roles:
                present = connection.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname=:name"), {"name": role}
                ).first()
                if not present:
                    connection.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN')
        apply_schema(
            self.engine,
            seed=False,
            api_role="lab20ci_api_role",
            api_user="lab20ci_api_user",
            worker_role="lab20ci_worker_role",
            worker_user="lab20ci_worker_user",
        )
        with self.engine.connect() as connection:
            api_updates_slots = connection.execute(
                text("SELECT has_table_privilege(:user, 'slots', 'UPDATE')"),
                {"user": "lab20ci_api_user"},
            ).scalar_one()
            worker_updates_slots = connection.execute(
                text("SELECT has_table_privilege(:user, 'slots', 'UPDATE')"),
                {"user": "lab20ci_worker_user"},
            ).scalar_one()
            worker_updates_bookings = connection.execute(
                text("SELECT has_table_privilege(:user, 'bookings', 'UPDATE')"),
                {"user": "lab20ci_worker_user"},
            ).scalar_one()
            worker_reads_bookings = connection.execute(
                text("SELECT has_table_privilege(:user, 'bookings', 'SELECT')"),
                {"user": "lab20ci_worker_user"},
            ).scalar_one()
        self.assertTrue(api_updates_slots)
        self.assertFalse(worker_updates_slots)
        self.assertFalse(worker_updates_bookings)
        self.assertTrue(worker_reads_bookings)

    def test_booking_is_idempotent_and_capacity_is_enforced(self):
        first = self.booking("one@example.test", "booking-key-0001")
        replay = self.booking("one@example.test", "booking-key-0001")
        second = self.booking("two@example.test", "booking-key-0002")
        full = self.booking("three@example.test", "booking-key-0003")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json["replayed"])
        self.assertEqual(second.status_code, 201)
        self.assertEqual(full.status_code, 409)
        self.assertEqual(full.json["error"], "slot_full")

    def test_same_idempotency_key_cannot_change_slot(self):
        self.assertEqual(self.booking("one@example.test", "booking-key-0101").status_code, 201)
        conflict = self.booking("one@example.test", "booking-key-0101", "consult-afternoon")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json["error"], "idempotency_key_conflict")

    def test_cancel_releases_capacity_and_replay_is_safe(self):
        created = self.booking("one@example.test", "booking-key-1001")
        booking_id = created.json["booking"]["booking_id"]
        headers = {"X-Test-User": "one@example.test"}
        cancelled = self.api.post(f"/api/bookings/{booking_id}/cancel", headers=headers)
        replay = self.api.post(f"/api/bookings/{booking_id}/cancel", headers=headers)
        self.assertEqual(cancelled.status_code, 200)
        self.assertFalse(cancelled.json["replayed"])
        self.assertTrue(replay.json["replayed"])
        self.assertEqual(self.booking("two@example.test", "booking-key-1002").status_code, 201)

    def test_report_moves_from_queued_to_ready_and_download_is_private(self):
        self.assertEqual(self.booking("one@example.test", "booking-key-2001").status_code, 201)
        report_date = datetime.now(timezone.utc).date().isoformat()
        accepted = self.api.post(
            "/api/reports",
            json={"report_date": report_date},
            headers={"X-Test-User": "one@example.test", "Idempotency-Key": "report-key-2001"},
        )
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(accepted.json["status"], "queued")
        topic, data = self.publisher.events[0]
        self.assertIn("/topics/", topic)
        envelope = {"message": {"data": base64.b64encode(data).decode("ascii")}}
        worker_response = self.worker.post("/events/reports", json=envelope)
        self.assertEqual(worker_response.status_code, 204)
        report_id = accepted.json["report_id"]
        status = self.api.get(
            f"/api/reports/{report_id}", headers={"X-Test-User": "one@example.test"}
        )
        self.assertEqual(status.json["report"]["status"], "ready")
        download = self.api.get(
            f"/api/reports/{report_id}/download", headers={"X-Test-User": "one@example.test"}
        )
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"booking_id,slot_id,status,created_at", download.data)
        forbidden = self.api.get(
            f"/api/reports/{report_id}", headers={"X-Test-User": "other@example.test"}
        )
        self.assertEqual(forbidden.status_code, 404)
        self.assertEqual(self.worker.post("/events/reports", json=envelope).status_code, 204)

    def test_invalid_report_date_and_missing_identity_are_rejected(self):
        invalid = self.api.post(
            "/api/reports",
            json={"report_date": "2026-99-99"},
            headers={"X-Test-User": "one@example.test", "Idempotency-Key": "report-key-3001"},
        )
        self.assertEqual(invalid.status_code, 400)
        protected = create_app(
            engine=self.engine,
            publisher=self.publisher,
            storage=self.storage,
            identity_resolver=lambda: None,
        ).test_client()
        self.assertEqual(protected.get("/api/slots").status_code, 401)

    def test_worker_rejects_malformed_and_unknown_messages(self):
        self.assertEqual(self.worker.post("/events/reports", json={"not": "a message"}).status_code, 400)
        bad_data = {"message": {"data": base64.b64encode(b"[]").decode("ascii")}}
        self.assertEqual(self.worker.post("/events/reports", json=bad_data).status_code, 400)
        unknown = {"message": {"data": base64.b64encode(b'{"schema_version":2}').decode("ascii")}}
        self.assertEqual(self.worker.post("/events/reports", json=unknown).status_code, 400)
        invalid_date = {
            "message": {
                "data": base64.b64encode(
                    b'{"schema_version":1,"report_id":"0123456789abcdef0123456789abcdef","report_date":"2026-99-99"}'
                ).decode("ascii")
            }
        }
        self.assertEqual(self.worker.post("/events/reports", json=invalid_date).status_code, 400)


if __name__ == "__main__":
    unittest.main()
