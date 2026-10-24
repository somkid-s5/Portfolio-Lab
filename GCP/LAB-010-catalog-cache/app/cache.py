import json
import os
import time

import redis
from redis.exceptions import RedisError

NAMESPACE = "catalog:v1:"
MAX_CATALOG_PRODUCTS = 2000
MAX_CATALOG_KEYS = 2104


class CacheGateway:
    def __init__(self, client, enabled=True, failure_threshold=3, open_seconds=15, clock=None):
        self.client = client
        self.enabled = enabled and client is not None
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self.clock = clock or time.monotonic
        self.consecutive_failures = 0
        self.open_until = 0.0

    def _available(self):
        if not self.enabled:
            return False, "disabled"
        if self.clock() < self.open_until:
            return False, "circuit_open"
        return True, None

    def _failure(self, error):
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.open_until = self.clock() + self.open_seconds
        return type(error).__name__

    def _success(self):
        self.consecutive_failures = 0
        self.open_until = 0.0

    def get(self, key):
        available, reason = self._available()
        if not available:
            return {"status": "BYPASS", "value": None, "error": reason}
        try:
            raw = self.client.get(key)
        except RedisError as error:
            return {"status": "BYPASS", "value": None, "error": self._failure(error)}
        self._success()
        if raw is None:
            return {"status": "MISS", "value": None, "error": None}
        try:
            return {"status": "HIT", "value": json.loads(raw), "error": None}
        except (TypeError, ValueError):
            return {"status": "MISS", "value": None, "error": "InvalidCachePayload"}

    def set(self, key, value, ttl_seconds):
        available, reason = self._available()
        if not available:
            return {"ok": False, "error": reason}
        try:
            self.client.setex(key, ttl_seconds, json.dumps(value, separators=(",", ":"), sort_keys=True))
        except RedisError as error:
            return {"ok": False, "error": self._failure(error)}
        self._success()
        return {"ok": True, "error": None}

    def delete(self, keys):
        unique = list(dict.fromkeys(keys))
        if not unique:
            return {"ok": True, "deleted": 0, "error": None}
        if any(not key.startswith(NAMESPACE) for key in unique):
            raise ValueError("Cache deletion is restricted to catalog:v1.")
        available, reason = self._available()
        if not available:
            return {"ok": False, "deleted": 0, "error": reason}
        deleted = 0
        try:
            for start in range(0, len(unique), 250):
                deleted += self.client.delete(*unique[start:start + 250])
        except RedisError as error:
            return {"ok": False, "deleted": deleted, "error": self._failure(error)}
        self._success()
        return {"ok": True, "deleted": deleted, "error": None}

    def clear_catalog(self, product_ids, categories):
        identifiers = list(dict.fromkeys(product_ids))
        allowed_categories = set(categories)
        if len(identifiers) > MAX_CATALOG_PRODUCTS:
            return {"ok": False, "deleted": 0, "error": "CatalogProductLimitExceeded"}
        if any(not isinstance(value, int) or not 1 <= value <= MAX_CATALOG_PRODUCTS
               for value in identifiers):
            raise ValueError("Product IDs are outside the catalog bounds.")
        if not allowed_categories.issubset({"books", "electronics", "home", "sports"}):
            raise ValueError("Category list is outside the catalog allowlist.")
        if len(identifiers) + len(allowed_categories) > MAX_CATALOG_KEYS:
            return {"ok": False, "deleted": 0, "error": "NamespaceKeyLimitExceeded"}
        keys = [f"{NAMESPACE}product:{product_id}" for product_id in identifiers]
        keys.extend(f"{NAMESPACE}list:{category}" for category in sorted(allowed_categories))
        return self.delete(keys)

    def invalidate_product(self, product_id, old_category, new_category):
        categories = {old_category, new_category}
        keys = [f"{NAMESPACE}product:{product_id}"]
        keys.extend(f"{NAMESPACE}list:{category}" for category in categories)
        return self.delete(keys)


def create_cache_gateway():
    enabled = time_env("CACHE_ENABLED", "true") == "true"
    if not enabled:
        return CacheGateway(None, enabled=False)
    url = os.getenv("REDIS_URL")
    if url:
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
            retry_on_timeout=False,
            retry_on_error=[],
            max_connections=20,
        )
        return CacheGateway(client)
    host = os.environ.get("REDIS_HOST")
    if not host:
        return CacheGateway(None, enabled=False)
    auth_file = os.environ.get("REDIS_AUTH_FILE")
    ca_file = os.environ.get("REDIS_CA_FILE")
    password = read_secret(auth_file) if auth_file else None
    if not ca_file:
        raise RuntimeError("REDIS_CA_FILE must point to the Memorystore server CA.")
    client = redis.Redis(
        host=host,
        port=int(os.environ.get("REDIS_PORT", "6378")),
        password=password,
        ssl=True,
        ssl_ca_certs=ca_file,
        ssl_cert_reqs="required",
        ssl_check_hostname=False,
        decode_responses=True,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
        retry_on_timeout=False,
        retry_on_error=[],
        max_connections=20,
    )
    return CacheGateway(client)


def read_secret(path):
    with open(path, "r", encoding="utf-8") as secret_file:
        return secret_file.read().strip()


def time_env(name, default):
    import os

    return os.environ.get(name, default).strip().lower()
