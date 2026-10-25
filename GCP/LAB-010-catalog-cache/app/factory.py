import json
import os
import re
import time
import uuid

from flask import Flask, current_app, g, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError

from app import catalog
from app.cache import CacheGateway, create_cache_gateway
from app.database import check_database, create_database_engine

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _record_cache(result):
    g.cache_status = result
    return result


def _cache_ttl(category=None):
    if category is None:
        return 60
    import os

    return max(1, min(60, int(os.environ.get("CATEGORY_LIST_TTL_SECONDS", "60"))))


def create_app(role="public", engine=None, cache=None):
    if role not in {"public", "admin"}:
        raise ValueError("role must be public or admin")
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["ROLE"] = role
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    app.extensions["db_engine"] = engine or create_database_engine()
    app.extensions["catalog_cache"] = cache if cache is not None else create_cache_gateway()

    @app.before_request
    def start_request():
        g.started_at = time.perf_counter()
        candidate = request.headers.get("X-Lab-Run-ID", "")
        g.lab_run_id = candidate if RUN_ID_PATTERN.fullmatch(candidate) else "unlabeled"
        candidate_request_id = request.headers.get("X-Request-ID", "")
        g.request_id = (
            candidate_request_id
            if RUN_ID_PATTERN.fullmatch(candidate_request_id)
            else str(uuid.uuid4())
        )
        g.cache_status = "SKIP"
        g.cache_error = None
        g.db_reads = 0
        g.db_ms = 0.0
        g.error_class = None

    @app.after_request
    def finish_request(response):
        response.headers["X-Request-ID"] = g.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Cache"] = g.cache_status
        fields = {
            "severity": "INFO" if response.status_code < 500 else "ERROR",
            "event": "catalog_request",
            "request_id": g.request_id,
            "lab_run_id": g.lab_run_id,
            "service_role": role,
            "method": request.method,
            "path": request.path,
            "cache_status": g.cache_status,
            "cache_error": g.cache_error,
            "db_reads": g.db_reads,
            "db_ms": round(g.db_ms, 3),
            "total_ms": round((time.perf_counter() - g.started_at) * 1000, 3),
            "status_code": response.status_code,
            "error_class": g.error_class,
        }
        print(json.dumps(fields, separators=(",", ":"), sort_keys=True), flush=True)
        return response

    def safe_service_error():
        g.error_class = "DatabaseUnavailable"
        return jsonify({"error": "service temporarily unavailable", "request_id": g.request_id}), 503

    def cached_response(key, loader, ttl_seconds):
        cache_gateway = current_app.extensions["catalog_cache"]
        hit = cache_gateway.get(key)
        _record_cache(hit["status"])
        g.cache_error = hit["error"]
        if hit["status"] == "HIT":
            return hit["value"]
        g.db_reads += 1
        started = time.perf_counter()
        try:
            value = loader(current_app.extensions["db_engine"])
        except SQLAlchemyError as error:
            g.error_class = type(error).__name__
            raise
        finally:
            g.db_ms += (time.perf_counter() - started) * 1000
        if value is not None and hit["status"] == "MISS":
            write = cache_gateway.set(key, value, ttl_seconds)
            if not write["ok"]:
                _record_cache("BYPASS")
                g.cache_error = write["error"]
        return value

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "alive", "role": role})

    @app.get("/readyz")
    def readyz():
        try:
            check_database(current_app.extensions["db_engine"])
        except SQLAlchemyError:
            g.error_class = "DatabaseUnavailable"
            return jsonify({"status": "not-ready"}), 503
        return jsonify({"status": "ready", "database": "ready", "cache": "optional"})

    if role == "public":
        @app.get("/")
        def home():
            return render_template("index.html")

        @app.get("/api/catalog")
        def category_listing():
            category = request.args.get("category", "")
            if category not in catalog.CATEGORIES:
                return jsonify({"error": "category must be one of the supported catalog categories"}), 400
            value = cached_response(
                f"catalog:v1:list:{category}",
                lambda db: [catalog.public_product(row) for row in catalog.get_category_products(db, category)],
                _cache_ttl(category),
            )
            return jsonify({"category": category, "items": value, "count": len(value)})

        @app.get("/api/products/<int:product_id>")
        def product_detail(product_id):
            if product_id < 1 or product_id > catalog.PRODUCT_COUNT:
                return jsonify({"error": "product not found"}), 404
            value = cached_response(
                f"catalog:v1:product:{product_id}",
                lambda db: (
                    catalog.public_product(row)
                    if (row := catalog.get_product(db, product_id)) is not None
                    else None
                ),
                _cache_ttl(),
            )
            if value is None:
                return jsonify({"error": "product not found"}), 404
            return jsonify(value)

    else:
        @app.put("/admin/products/<int:product_id>")
        def update(product_id):
            if_match = request.headers.get("If-Match", "")
            if_match = if_match.strip().strip('"')
            if not if_match.isdigit():
                return jsonify({"error": "If-Match must contain the expected product version"}), 428
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 415
            changes = request.get_json(silent=True)
            if not isinstance(changes, dict):
                return jsonify({"error": "request body must be a JSON object"}), 400
            g.db_reads += 1
            started = time.perf_counter()
            try:
                updated, old_category = catalog.update_product(
                    current_app.extensions["db_engine"], product_id, int(if_match), changes
                )
            except catalog.ProductNotFound:
                return jsonify({"error": "product not found"}), 404
            except catalog.VersionConflict:
                return jsonify({"error": "product version changed; fetch the current version and retry"}), 412
            except ValueError as error:
                return jsonify({"error": str(error)}), 400
            except SQLAlchemyError:
                return safe_service_error()
            finally:
                g.db_ms += (time.perf_counter() - started) * 1000

            invalidation = current_app.extensions["catalog_cache"].invalidate_product(
                product_id, old_category, updated["category"]
            )
            g.cache_status = "INVALIDATED" if invalidation["ok"] else "INVALIDATION_NOT_CONFIRMED"
            g.cache_error = invalidation["error"]
            body = {
                "product": catalog.public_product(updated),
                "cache_invalidation": "confirmed" if invalidation["ok"] else "not_confirmed",
                "stale_bound_seconds": 0 if invalidation["ok"] else 60,
            }
            return jsonify(body)

        @app.get("/admin/cache/ttl/<category>")
        def inspect_category_ttl(category):
            if category not in catalog.CATEGORIES:
                return jsonify({"error": "category must be one of the supported catalog categories"}), 400
            key = f"catalog:v1:list:{category}"
            result = current_app.extensions["catalog_cache"].inspect_list_ttl(key)
            if not result["ok"]:
                g.cache_status = "BYPASS"
                g.cache_error = result["error"]
                return jsonify({"status": "unavailable", "reason": result["error"]}), 503
            g.cache_status = "INSPECTED"
            ttl_seconds = result["ttl_seconds"]
            ttl_state = "missing" if ttl_seconds == -2 else "persistent" if ttl_seconds == -1 else "expiring"
            return jsonify({
                "key": key,
                "ttl_seconds": ttl_seconds,
                "ttl_state": ttl_state,
            })

        @app.post("/admin/cache/clear")
        def clear_cache():
            engine = current_app.extensions["db_engine"]
            g.db_reads += 1
            started = time.perf_counter()
            try:
                identifiers = catalog.list_product_ids(engine)
            except SQLAlchemyError:
                return safe_service_error()
            finally:
                g.db_ms += (time.perf_counter() - started) * 1000
            result = current_app.extensions["catalog_cache"].clear_catalog(
                identifiers, catalog.CATEGORIES
            )
            g.cache_status = "CLEARED" if result["ok"] else "CLEAR_NOT_CONFIRMED"
            g.cache_error = result["error"]
            return jsonify({
                "namespace": "catalog:v1",
                "cleared_keys": result["deleted"],
                "status": "confirmed" if result["ok"] else "not_confirmed",
            })

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        g.error_class = type(error).__name__
        return safe_service_error()

    return app
