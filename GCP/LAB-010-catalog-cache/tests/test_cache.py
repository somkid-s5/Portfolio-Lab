import unittest

import redis

from app.cache import CacheGateway


class FakeRedis:
    def __init__(self):
        self.fail = True
        self.values = {}

    def get(self, key):
        if self.fail:
            raise redis.ConnectionError("test failure")
        return self.values.get(key)

    def setex(self, key, ttl, value):
        if self.fail:
            raise redis.ConnectionError("test failure")
        self.values[key] = value
        self.last_ttl = ttl

    def delete(self, *keys):
        if self.fail:
            raise redis.ConnectionError("test failure")
        return sum(self.values.pop(key, None) is not None for key in keys)

class CircuitBreakerTests(unittest.TestCase):
    def test_three_failures_open_circuit_and_recovery_after_cooldown(self):
        now = [100.0]
        client = FakeRedis()
        cache = CacheGateway(client, clock=lambda: now[0])
        self.assertEqual(cache.get("catalog:v1:product:1")["status"], "BYPASS")
        self.assertEqual(cache.get("catalog:v1:product:1")["status"], "BYPASS")
        self.assertEqual(cache.get("catalog:v1:product:1")["status"], "BYPASS")
        self.assertEqual(cache.get("catalog:v1:product:1")["error"], "circuit_open")
        client.fail = False
        now[0] += 15
        self.assertEqual(cache.get("catalog:v1:product:1")["status"], "MISS")
        self.assertEqual(cache.set("catalog:v1:product:1", {"id": 1}, 60)["ok"], True)
        self.assertEqual(client.last_ttl, 60)

    def test_ttl_inspection_rejects_non_list_keys(self):
        cache = CacheGateway(FakeRedis())
        with self.assertRaises(ValueError):
            cache.inspect_list_ttl("catalog:v1:product:1")

    def test_delete_is_restricted_to_catalog_namespace(self):
        cache = CacheGateway(FakeRedis())
        with self.assertRaises(ValueError):
            cache.delete(["unrelated:key"])

    def test_clear_only_deletes_bounded_catalog_keys(self):
        client = FakeRedis()
        client.fail = False
        client.values = {"catalog:v1:product:1": "{}", "other:key": "safe"}
        result = CacheGateway(client).clear_catalog([1], ["books", "electronics", "home", "sports"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["deleted"], 1)
        self.assertIn("other:key", client.values)

    def test_clear_refuses_product_ids_outside_lab_bounds(self):
        cache = CacheGateway(FakeRedis())
        with self.assertRaises(ValueError):
            cache.clear_catalog([2001], ["books"])


if __name__ == "__main__":
    unittest.main()
