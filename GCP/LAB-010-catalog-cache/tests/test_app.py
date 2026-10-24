import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import redis
from sqlalchemy import text, update
from sqlalchemy.exc import OperationalError

from app import catalog
from app.cache import CacheGateway
from app.database import close_database_engine, create_database_engine
from app.factory import create_app
from app.schema import metadata, products


class BrokenRedis:
    def get(self, key):
        raise redis.ConnectionError("synthetic Redis unavailable")

    def setex(self, key, ttl, value):
        raise redis.ConnectionError("synthetic Redis unavailable")

    def delete(self, *keys):
        raise redis.ConnectionError("synthetic Redis unavailable")


class DeleteFailureRedis:
    def __init__(self, client):
        self.client = client

    def get(self, key):
        return self.client.get(key)

    def setex(self, key, ttl, value):
        return self.client.setex(key, ttl, value)

    def delete(self, *keys):
        raise redis.ConnectionError("synthetic invalidation failure")


class CatalogIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_database_engine()
        metadata.create_all(cls.engine)
        catalog.seed_catalog(cls.engine)
        cls.redis_client = redis.Redis.from_url(
            os.environ["REDIS_URL"],
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
        )
        cls.cache = CacheGateway(cls.redis_client)
        cls.public_app = create_app("public", engine=cls.engine, cache=cls.cache)
        cls.admin_app = create_app("admin", engine=cls.engine, cache=cls.cache)
        cls.public_app.testing = True
        cls.admin_app.testing = True

    @classmethod
    def tearDownClass(cls):
        cls.redis_client.close()
        close_database_engine(cls.engine)

    def setUp(self):
        self.cache.clear_catalog(range(1, 2001), catalog.CATEGORIES)
        with self.engine.begin() as connection:
            connection.execute(
                update(products)
                .where(products.c.id == 1)
                .values(
                    category="books",
                    name="Books Item 0001",
                    description="Synthetic catalog metadata for test.",
                    image_url="/static/product-placeholder.svg",
                    active=True,
                    version=1,
                )
            )
        self.public = self.public_app.test_client()
        self.admin = self.admin_app.test_client()

    def test_detail_and_listing_use_cache_and_ttl(self):
        first = self.public.get("/api/products/1")
        second = self.public.get("/api/products/1")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["X-Cache"], "MISS")
        self.assertEqual(second.headers["X-Cache"], "HIT")
        self.assertEqual(second.json["version"], 1)
        self.assertGreaterEqual(self.redis_client.ttl("catalog:v1:product:1"), 1)
        self.assertLessEqual(self.redis_client.ttl("catalog:v1:product:1"), 60)

        listing = self.public.get("/api/catalog?category=books")
        again = self.public.get("/api/catalog?category=books")
        self.assertEqual(listing.headers["X-Cache"], "MISS")
        self.assertEqual(again.headers["X-Cache"], "HIT")
        self.assertEqual(listing.json["count"], 50)

    def test_category_validation_health_and_scoped_clear(self):
        bad = self.public.get("/api/catalog?category=unknown")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.public.get("/healthz").status_code, 200)
        self.assertEqual(self.public.get("/readyz").status_code, 200)
        self.redis_client.set("other:v1:keep", "safe")
        self.public.get("/api/products/1")
        cleared = self.admin.post("/admin/cache/clear")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json["status"], "confirmed")
        self.assertIsNotNone(self.redis_client.get("other:v1:keep"))
        self.assertIsNone(self.redis_client.get("catalog:v1:product:1"))

    def test_update_requires_version_and_invalidates_old_and_new_categories(self):
        self.public.get("/api/products/1")
        self.public.get("/api/catalog?category=books")
        self.public.get("/api/catalog?category=sports")
        missing_version = self.admin.put("/admin/products/1", json={"name": "New name"})
        self.assertEqual(missing_version.status_code, 428)

        response = self.admin.put(
            "/admin/products/1",
            headers={"If-Match": '"1"'},
            json={"category": "sports", "name": "Trail guide"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["product"]["version"], 2)
        self.assertEqual(response.json["cache_invalidation"], "confirmed")
        detail = self.public.get("/api/products/1")
        old_list = self.public.get("/api/catalog?category=books")
        new_list = self.public.get("/api/catalog?category=sports")
        self.assertEqual(detail.headers["X-Cache"], "MISS")
        self.assertEqual(detail.json["name"], "Trail guide")
        self.assertEqual(old_list.headers["X-Cache"], "MISS")
        self.assertEqual(new_list.headers["X-Cache"], "MISS")

    def test_invalidation_failure_reports_stale_bound_and_db_commit(self):
        self.public.get("/api/products/1")
        previous = self.admin_app.extensions["catalog_cache"]
        self.admin_app.extensions["catalog_cache"] = CacheGateway(
            DeleteFailureRedis(self.redis_client)
        )
        try:
            response = self.admin.put(
                "/admin/products/1",
                headers={"If-Match": '"1"'},
                json={"name": "Committed while cache is unavailable"},
            )
        finally:
            self.admin_app.extensions["catalog_cache"] = previous
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["product"]["version"], 2)
        self.assertEqual(response.json["cache_invalidation"], "not_confirmed")
        self.assertEqual(response.json["stale_bound_seconds"], 60)
        stale = self.public.get("/api/products/1")
        self.assertEqual(stale.headers["X-Cache"], "HIT")
        self.assertEqual(stale.json["version"], 1)
        ttl = self.redis_client.ttl("catalog:v1:product:1")
        self.assertGreaterEqual(ttl, 1)
        self.assertLessEqual(ttl, 60)

    def test_stale_if_match_is_rejected(self):
        first = self.admin.put(
            "/admin/products/1",
            headers={"If-Match": '"1"'},
            json={"name": "Updated once"},
        )
        second = self.admin.put(
            "/admin/products/1",
            headers={"If-Match": '"1"'},
            json={"name": "Stale write"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 412)

    def test_redis_failure_falls_back_to_database_without_leaking_details(self):
        previous = self.public_app.extensions["catalog_cache"]
        self.public_app.extensions["catalog_cache"] = CacheGateway(BrokenRedis())
        try:
            response = self.public.get("/api/products/1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Cache"], "BYPASS")
            self.assertEqual(response.json["id"], 1)
            self.assertNotIn("unavailable", response.get_data(as_text=True).lower())
        finally:
            self.public_app.extensions["catalog_cache"] = previous

    def test_database_error_is_sanitized(self):
        output = io.StringIO()
        with patch(
            "app.factory.catalog.get_product",
            side_effect=OperationalError("select", {}, RuntimeError("password=do-not-log")),
        ), redirect_stdout(output):
            response = self.public.get("/api/products/1")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("do-not-log", response.get_data(as_text=True))
        self.assertNotIn("do-not-log", output.getvalue())
        self.assertIn('"error_class":"DatabaseUnavailable"', output.getvalue())

    def test_logs_contain_measurement_fields_not_catalog_payload(self):
        output = io.StringIO()
        with redirect_stdout(output):
            response = self.public.get(
                "/api/products/1",
                headers={"X-Lab-Run-ID": "test-run_1"},
            )
        self.assertEqual(response.status_code, 200)
        event = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertEqual(event["lab_run_id"], "test-run_1")
        self.assertIn("cache_status", event)
        self.assertIn("db_reads", event)
        self.assertIn("db_ms", event)
        self.assertIn("total_ms", event)
        self.assertNotIn("Books Item 0001", output.getvalue())


class RuntimeGrantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_database_engine()
        cls.reader = "lab10_reader_ci"
        cls.operator = "lab10_operator_ci"
        with cls.engine.begin() as connection:
            connection.execute(text(f'CREATE ROLE "{cls.reader}" NOLOGIN'))
            connection.execute(text(f'CREATE ROLE "{cls.operator}" NOLOGIN'))

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{cls.reader}"'))
            connection.execute(text(f'DROP OWNED BY "{cls.operator}"'))
            connection.execute(text(f'DROP ROLE "{cls.reader}"'))
            connection.execute(text(f'DROP ROLE "{cls.operator}"'))
        close_database_engine(cls.engine)

    def test_runtime_grants_are_separated_and_column_scoped(self):
        from app.migrate import grant_runtime_access

        grant_runtime_access(
            self.engine,
            os.environ.get("DB_NAME", "lab010_ci"),
            self.reader,
            self.operator,
        )
        with self.engine.connect() as connection:
            checks = connection.execute(
                text("""
                    SELECT
                      has_database_privilege(:reader, current_database(), 'CONNECT'),
                      has_schema_privilege(:reader, 'public', 'USAGE'),
                      has_table_privilege(:reader, 'public.products', 'SELECT'),
                      has_table_privilege(:reader, 'public.products', 'UPDATE'),
                      has_table_privilege(:operator, 'public.products', 'SELECT'),
                      has_table_privilege(:operator, 'public.products', 'UPDATE'),
                      has_column_privilege(:operator, 'public.products', 'name', 'UPDATE'),
                      has_column_privilege(:operator, 'public.products', 'version', 'UPDATE'),
                      has_column_privilege(:operator, 'public.products', 'id', 'UPDATE')
                """),
                {"reader": self.reader, "operator": self.operator},
            ).one()
        self.assertEqual(tuple(checks), (True, True, True, False, True, False, True, True, False))

    def test_identifier_validation_rejects_sql_injection_and_duplicate_roles(self):
        from app.migrate import grant_runtime_access, quote_identifier

        for value in ('reader"; DROP TABLE products;--', "bad role", "toolong" + "a" * 63):
            with self.subTest(value=value), self.assertRaises(ValueError):
                quote_identifier(value)
        with self.assertRaises(ValueError):
            grant_runtime_access(self.engine, "catalog", "same", "same")


if __name__ == "__main__":
    unittest.main()
