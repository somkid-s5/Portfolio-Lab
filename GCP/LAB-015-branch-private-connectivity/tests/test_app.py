from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.inventory_api import create_handler


class InventoryApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler())
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get_json(self, path):
        with urlopen(self.base + path, timeout=2) as response:
            return response.status, json.load(response)

    def test_health_endpoint(self):
        status, payload = self.get_json("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "lab015-inventory")
        self.assertTrue(payload["request_id"])

    def test_lists_seed_inventory_and_filters_by_sku(self):
        status, payload = self.get_json("/v1/items")
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 3)
        status, payload = self.get_json("/v1/items?sku=SKU-100")
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["available"], 17)

    def test_unknown_item_is_not_found(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/v1/items/NOT-A-SKU", timeout=2)
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(json.loads(caught.exception.read())["error"], "item_not_found")

    def test_api_is_read_only(self):
        request = Request(self.base + "/v1/items", data=b"{}", method="POST")
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 405)

    def test_unknown_path_is_not_found(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/not-a-route", timeout=2)
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
