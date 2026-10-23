"""Strict order/event contracts. No I/O, credentials or business-state mutation."""
import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
import re

MAX_BODY = 4096
MAX_PUSH = 65536


class Rejected(ValueError):
    """Safe code only; never includes raw request or credentials."""
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Rejected("duplicate_json_key")
        result[key] = value
    return result


def read_json(body, *, limit=MAX_BODY):
    if not isinstance(body, bytes):
        raise TypeError("body_must_be_bytes")
    if not 1 <= len(body) <= limit:
        raise Rejected("invalid_body_size")
    try:
        value = json.loads(
            body.decode("utf-8"), object_pairs_hook=_object,
            parse_constant=lambda _: (_ for _ in ()).throw(Rejected("invalid_json")))
    except (UnicodeError, ValueError, RecursionError):
        raise Rejected("invalid_json") from None
    if not isinstance(value, dict):
        raise Rejected("invalid_json_object")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise Rejected("invalid_identifier")
    return value


def owner_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value):
        raise Rejected("invalid_owner")
    return value


def _items(value, *, priced=False):
    if not isinstance(value, list) or not 1 <= len(value) <= 2:
        raise Rejected("invalid_items")
    result = []
    seen = set()
    fields = {"sku", "quantity"} | ({"unit_price_satang"} if priced else set())
    for item in value:
        if not isinstance(item, dict) or set(item) != fields:
            raise Rejected("invalid_item_fields")
        sku = item["sku"]
        if not isinstance(sku, str) or not re.fullmatch(r"[A-Z][A-Z0-9-]{0,31}", sku):
            raise Rejected("invalid_sku")
        if sku in seen:
            raise Rejected("duplicate_sku")
        seen.add(sku)
        quantity = item["quantity"]
        if type(quantity) is not int or not 1 <= quantity <= 3:
            raise Rejected("invalid_quantity")
        normalized = {"sku": sku, "quantity": quantity}
        if priced:
            price = item["unit_price_satang"]
            if type(price) is not int or not 0 <= price <= 100000000:
                raise Rejected("invalid_price")
            normalized["unit_price_satang"] = price
        result.append(normalized)
    return sorted(result, key=lambda item: item["sku"])


@dataclass(frozen=True)
class CreateOrder:
    idempotency_key: str
    items: tuple
    request_fingerprint: str


def create_order(body):
    value = read_json(body)
    if set(value) != {"idempotency_key", "items"}:
        raise Rejected("invalid_order_fields")
    key = identifier(value["idempotency_key"])
    items = _items(value["items"])
    fingerprint = hashlib.sha256(canonical({"items": items})).hexdigest()
    return CreateOrder(key, tuple((i["sku"], i["quantity"]) for i in items), fingerprint)


def key_hash(owner, key):
    return hashlib.sha256((owner_name(owner)+":"+identifier(key)).encode("ascii")).hexdigest()


def order_binding(owner, order_id, priced_items):
    """Price snapshot comes from locked/catalog database data, never client price."""
    items = _items(priced_items, priced=True)
    data = {"owner": owner_name(owner), "order_id": identifier(order_id),
            "items": items}
    total = sum(item["quantity"]*item["unit_price_satang"] for item in items)
    return items, hashlib.sha256(canonical(data)).hexdigest(), total


@dataclass(frozen=True)
class OrderEvent:
    event_id: str
    order_id: str
    order_fingerprint: str


def parse_event(body):
    value = read_json(body)
    if set(value) != {"schema_version", "event_id", "order_id", "order_fingerprint"}:
        raise Rejected("invalid_event_fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Rejected("unsupported_schema_version")
    fingerprint = value["order_fingerprint"]
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise Rejected("invalid_fingerprint")
    return OrderEvent(identifier(value["event_id"]), identifier(value["order_id"]),
                      fingerprint)


def event_bytes(event_id, order_id, fingerprint):
    body = canonical({"schema_version": 1, "event_id": event_id,
                      "order_id": order_id, "order_fingerprint": fingerprint})
    parse_event(body)
    return body


@dataclass(frozen=True)
class Delivery:
    message_id: str
    delivery_attempt: int | None
    event: OrderEvent


def parse_push(body, expected_subscription):
    """Must run behind Cloud Run IAM. JSON fields are NOT authentication."""
    if not isinstance(expected_subscription, str) or not re.fullmatch(
            r"projects/[a-z0-9-]{6,63}/subscriptions/[A-Za-z][A-Za-z0-9._~-]{2,254}",
            expected_subscription):
        raise ValueError("invalid_subscription_configuration")
    value = read_json(body, limit=MAX_PUSH)
    if set(value) - {"message", "subscription", "deliveryAttempt"}:
        raise Rejected("invalid_push_fields")
    if value.get("subscription") != expected_subscription:
        raise Rejected("unexpected_subscription")
    message = value.get("message")
    if not isinstance(message, dict) or set(message) - {
            "data", "messageId", "message_id", "publishTime", "publish_time",
            "attributes", "orderingKey"}:
        raise Rejected("invalid_message")
    message_id = message.get("messageId", message.get("message_id"))
    if ("messageId" in message and "message_id" in message and
            message["messageId"] != message["message_id"]):
        raise Rejected("conflicting_message_id")
    if ("publishTime" in message and "publish_time" in message and
            message["publishTime"] != message["publish_time"]):
        raise Rejected("conflicting_publish_time")
    if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", message_id):
        raise Rejected("invalid_message_id")
    attributes = message.get("attributes", {})
    if (not isinstance(attributes, dict) or len(attributes) > 20 or
            any(not isinstance(k, str) or not isinstance(v, str) or
                len(k) > 128 or len(v) > 512 for k, v in attributes.items())):
        raise Rejected("invalid_attributes")
    encoded = message.get("data")
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= 5464:
        raise Rejected("invalid_event_size")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise Rejected("invalid_base64") from None
    event = parse_event(decoded)
    attempt = value.get("deliveryAttempt")
    if attempt is not None and (type(attempt) is not int or not 0 <= attempt <= 1000000):
        raise Rejected("invalid_delivery_attempt")
    return Delivery(message_id, attempt, event)
