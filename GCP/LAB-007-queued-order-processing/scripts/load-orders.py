"""Bounded synthetic order producer; stores idempotency keys before any POST."""
import argparse
import http.cookiejar
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from order_domain import canonical, identifier, read_json

MAX_ORDERS = 100
MAX_RATE = 2.0
MAX_SEND_SECONDS = 60
MAX_OBSERVE_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 5
CLOUD_RUN_HOST = re.compile(r"lab007-portal-[a-z0-9]+(?:[.-][a-z0-9]+)*\.run\.app")


class SafeFailure(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class OutcomeUnknown(SafeFailure):
    def __init__(self):
        super().__init__("order_outcome_unknown_reuse_journal")


class PortalFailure(SafeFailure):
    def __init__(self, code, status=None):
        super().__init__(code)
        self.status = status


def origin_url(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname or ""
        invalid = (parsed.scheme != "https" or parsed.username is not None
                   or parsed.password is not None or parsed.port is not None
                   or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                   or not CLOUD_RUN_HOST.fullmatch(host))
    except (AttributeError, TypeError, ValueError):
        raise SafeFailure("invalid_portal_origin") from None
    if invalid:
        raise SafeFailure("invalid_portal_origin")
    return "https://" + host


def ensure_private_parent(path):
    parent = Path(path).expanduser().parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix" and stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise SafeFailure("private_directory_required")
    return parent


def private_read(path, limit=65536):
    target = Path(path).expanduser()
    parent = target.parent
    if os.name == "posix" and stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise SafeFailure("private_directory_required")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode)
                or (os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077)):
            raise SafeFailure("private_regular_file_required")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise SafeFailure("private_file_too_large")
    try:
        return read_json(raw, limit=limit)
    except (TypeError, ValueError):
        raise SafeFailure("private_json_invalid") from None


def private_create(path, value):
    target = Path(path).expanduser()
    ensure_private_parent(target)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical(value))
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def private_replace(path, value):
    target = Path(path).expanduser()
    ensure_private_parent(target)
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        raise SafeFailure("journal_disappeared") from None
    if (not stat.S_ISREG(info.st_mode)
            or (os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077)):
        raise SafeFailure("private_regular_file_required")
    temporary = target.with_name("." + target.name + "." + uuid.uuid4().hex + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def validate_settings(count, sku, quantity, rate, observe_seconds):
    if type(count) is not int or not 1 <= count <= MAX_ORDERS:
        raise SafeFailure("count_out_of_bounds")
    if not isinstance(sku, str) or not re.fullmatch(r"[A-Z][A-Z0-9-]{0,31}", sku):
        raise SafeFailure("invalid_sku")
    if type(quantity) is not int or not 1 <= quantity <= 3:
        raise SafeFailure("quantity_out_of_bounds")
    if (type(rate) not in (int, float) or not math.isfinite(rate)
            or not 0.1 <= float(rate) <= MAX_RATE):
        raise SafeFailure("rate_out_of_bounds")
    if type(observe_seconds) is not int or not 0 <= observe_seconds <= MAX_OBSERVE_SECONDS:
        raise SafeFailure("observation_window_out_of_bounds")
    if (count - 1) / float(rate) > MAX_SEND_SECONDS:
        raise SafeFailure("requested_send_window_exceeds_60_seconds")
    return float(rate)


def new_journal(origin, customer, count, sku, quantity, rate, observe_seconds):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "run_id": uuid.uuid4().hex,
        "created_at": stamp,
        "origin": origin,
        "customer": customer,
        "count": count,
        "sku": sku,
        "quantity": quantity,
        "rate_per_second": float(rate),
        "observe_seconds": observe_seconds,
        "stock_before": None,
        "stock_after": None,
        "orders": [{
            "idempotency_key": uuid.uuid4().hex,
            "items": [{"sku": sku, "quantity": quantity}],
            "attempts": 0,
            "last_http_status": None,
            "order_id": None,
            "state": None,
            "replayed": None,
        } for _ in range(count)],
    }


def journal_identifier(value):
    try:
        return identifier(value)
    except (TypeError, ValueError):
        raise SafeFailure("journal_schema_invalid") from None


def validate_journal(value):
    fields = {"schema_version", "run_id", "created_at", "origin", "customer",
              "count", "sku", "quantity", "rate_per_second", "observe_seconds",
              "stock_before", "stock_after", "orders"}
    if (not isinstance(value, dict) or set(value) != fields
            or type(value["schema_version"]) is not int or value["schema_version"] != 1):
        raise SafeFailure("journal_schema_invalid")
    journal_identifier(value["run_id"])
    if not isinstance(value["created_at"], str) or len(value["created_at"]) > 40:
        raise SafeFailure("journal_schema_invalid")
    validate_settings(value["count"], value["sku"], value["quantity"],
                      value["rate_per_second"], value["observe_seconds"])
    for field in ("stock_before", "stock_after"):
        stock = value[field]
        if stock is not None and (type(stock) is not int or stock < 0):
            raise SafeFailure("journal_schema_invalid")
    if (not isinstance(value["customer"], str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value["customer"])):
        raise SafeFailure("journal_schema_invalid")
    if not isinstance(value["orders"], list) or len(value["orders"]) != value["count"]:
        raise SafeFailure("journal_schema_invalid")
    expected_items = [{"sku": value["sku"], "quantity": value["quantity"]}]
    for entry in value["orders"]:
        if (not isinstance(entry, dict)
                or set(entry) != {"idempotency_key", "items", "attempts",
                                  "last_http_status", "order_id", "state", "replayed"}
                or not isinstance(entry["items"], list) or len(entry["items"]) != 1
                or not isinstance(entry["items"][0], dict)
                or set(entry["items"][0]) != {"sku", "quantity"}
                or entry["items"][0].get("sku") != value["sku"]
                or type(entry["items"][0].get("quantity")) is not int
                or entry["items"][0].get("quantity") != value["quantity"]):
            raise SafeFailure("journal_schema_invalid")
        journal_identifier(entry["idempotency_key"])
        if type(entry["attempts"]) is not int or not 0 <= entry["attempts"] <= 3:
            raise SafeFailure("journal_schema_invalid")
        if entry["order_id"] is not None:
            journal_identifier(entry["order_id"])
        if entry["state"] not in (None, "accepted", "confirmed", "rejected"):
            raise SafeFailure("journal_schema_invalid")
        if entry["replayed"] is not None and type(entry["replayed"]) is not bool:
            raise SafeFailure("journal_schema_invalid")
        status = entry["last_http_status"]
        if status is not None and (type(status) is not int or not 100 <= status <= 599):
            raise SafeFailure("journal_schema_invalid")
        if entry["order_id"] is None and (entry["state"] is not None or entry["replayed"] is not None):
            raise SafeFailure("journal_schema_invalid")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise PortalFailure("redirect_refused")


class Portal:
    def __init__(self, origin, *, opener=None):
        self.origin = origin_url(origin)
        self.opener = opener or urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = None

    def request(self, path, body=None, timeout=HTTP_TIMEOUT_SECONDS):
        allowed = {"/api/session", "/api/login", "/api/catalog"}
        order_detail = re.fullmatch(r"/api/orders/[a-f0-9]{32}", path)
        order_list = path.startswith("/api/orders?limit=20") and len(path) <= 8192
        if path not in allowed and path != "/api/orders" and not order_detail and not order_list:
            raise PortalFailure("route_refused")
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["X-CSRF-Token"] = self.csrf or ""
            data = canonical(body)
        method = "POST" if body is not None else "GET"
        request = urllib.request.Request(self.origin + path, data=data,
                                         headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                status = response.status
                raw = response.read(65537)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            if method == "POST" and path == "/api/orders" and (status >= 500 or 300 <= status < 400):
                raise OutcomeUnknown() from None
            raise PortalFailure("portal_http_" + str(status), status) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if method == "POST" and path == "/api/orders":
                raise OutcomeUnknown() from None
            raise PortalFailure("portal_network_unavailable") from None
        except PortalFailure as failure:
            if method == "POST" and path == "/api/orders" and failure.code == "redirect_refused":
                raise OutcomeUnknown() from None
            raise
        if len(raw) > 65536:
            if method == "POST" and path == "/api/orders" and status in (200, 202):
                raise OutcomeUnknown() from None
            raise PortalFailure("portal_response_too_large", status)
        try:
            result = read_json(raw, limit=65536)
        except (TypeError, ValueError):
            if method == "POST" and path == "/api/orders" and status in (200, 202):
                raise OutcomeUnknown() from None
            raise PortalFailure("portal_response_invalid", status) from None
        return status, result

    def login(self, username, password):
        status, value = self.request("/api/session")
        if status != 200 or not isinstance(value.get("csrf"), str) or not re.fullmatch(
                r"[a-f0-9]{64}", value["csrf"]):
            raise PortalFailure("session_response_invalid", status)
        self.csrf = value["csrf"]
        status, value = self.request("/api/login", {"username": username, "password": password})
        if (status != 200 or value.get("user") != username or value.get("role") != "customer"
                or not isinstance(value.get("csrf"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", value["csrf"])):
            raise PortalFailure("customer_login_failed", status)
        self.csrf = value["csrf"]

    def catalog_available(self, sku):
        status, value = self.request("/api/catalog")
        items = value.get("items")
        if status != 200 or not isinstance(items, list) or len(items) > 50:
            raise PortalFailure("catalog_response_invalid", status)
        matching = [item for item in items if isinstance(item, dict) and item.get("sku") == sku]
        if len(matching) != 1 or type(matching[0].get("available")) is not int:
            raise PortalFailure("catalog_sku_unavailable")
        return matching[0]["available"]

    def create_order(self, entry):
        status, value = self.request("/api/orders", {
            "idempotency_key": entry["idempotency_key"], "items": entry["items"]})
        if (status not in (200, 202) or not isinstance(value, dict)
                or value.get("state") not in ("accepted", "confirmed", "rejected")
                or type(value.get("replayed")) is not bool):
            raise OutcomeUnknown()
        try:
            order_id = identifier(value.get("order_id"))
        except (TypeError, ValueError):
            raise OutcomeUnknown() from None
        return status, order_id, value["state"], value["replayed"]

    def orders_page(self, cursor, timeout):
        path = "/api/orders?limit=20"
        if cursor is not None:
            path += "&" + urllib.parse.urlencode({"cursor": cursor})
        status, value = self.request(path, timeout=timeout)
        items = value.get("items")
        next_cursor = value.get("next_cursor")
        if (status != 200 or not isinstance(items, list) or len(items) > 20
                or (next_cursor is not None and
                    (not isinstance(next_cursor, str) or not 1 <= len(next_cursor) <= 4096))):
            raise PortalFailure("order_page_invalid", status)
        return items, next_cursor


def load_or_create_journal(args, origin):
    target = Path(args.journal).expanduser()
    if args.resume:
        journal = validate_journal(private_read(target))
        if journal["origin"] != origin:
            raise SafeFailure("journal_origin_mismatch")
        for field in ("customer", "count", "sku", "quantity", "rate", "observe_seconds"):
            requested = getattr(args, field, None)
            stored = journal["rate_per_second"] if field == "rate" else journal.get(
                "observe_seconds" if field == "observe_seconds" else field)
            if requested is not None and requested != stored:
                raise SafeFailure("resume_options_mismatch")
        return target, journal
    if args.count is None:
        count = 10
    else:
        count = args.count
    sku = args.sku or "BOOK-01"
    quantity = args.quantity if args.quantity is not None else 1
    rate = args.rate if args.rate is not None else 1.0
    observe = args.observe_seconds if args.observe_seconds is not None else 30
    rate = validate_settings(count, sku, quantity, rate, observe)
    customer = args.customer or "alice"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", customer):
        raise SafeFailure("invalid_customer")
    journal = new_journal(origin, customer, count, sku, quantity, rate, observe)
    private_create(target, journal)
    return target, journal


def login_password(bundle_path, customer):
    bundle = private_read(bundle_path, limit=4096)
    record = bundle.get(customer) if isinstance(bundle, dict) else None
    if (not isinstance(record, dict) or set(record) != {"password", "role"}
            or record.get("role") != "customer" or not isinstance(record.get("password"), str)
            or not 24 <= len(record["password"]) <= 128):
        raise SafeFailure("private_customer_credential_missing")
    return record["password"]


def execute(args, *, client_factory=Portal, clock=time.monotonic,
            sleep_fn=time.sleep, emit=print):
    try:
        origin = origin_url(args.portal)
        journal_path, journal = load_or_create_journal(args, origin)
        password = login_password(args.demo_logins, journal["customer"])
        client = client_factory(origin)
        client.login(journal["customer"], password)
        available = client.catalog_available(journal["sku"])
        if journal["stock_before"] is None:
            journal["stock_before"] = available
            private_replace(journal_path, journal)
        unattempted = [entry for entry in journal["orders"] if entry["attempts"] == 0]
        demand = len(unattempted) * journal["quantity"]
        if available < demand:
            raise SafeFailure("insufficient_stock_for_unattempted_orders")

        started = clock()
        next_due = started
        stopped_at_window = False
        for entry in journal["orders"]:
            if entry["order_id"] is not None:
                continue
            if entry["attempts"] >= 3:
                raise SafeFailure("attempt_limit_reached_reconcile_in_portal")
            pause = next_due - clock()
            if pause > 0:
                sleep_fn(pause)
            if clock() - started >= MAX_SEND_SECONDS:
                stopped_at_window = True
                break
            entry["attempts"] += 1
            entry["last_http_status"] = None
            private_replace(journal_path, journal)
            next_due = clock() + 1.0 / journal["rate_per_second"]
            try:
                status, order_id, state, replayed = client.create_order(entry)
            except OutcomeUnknown:
                report = {"event": "order_outcome_unknown",
                          "run_id": journal["run_id"],
                          "next": "resume_with_same_journal_and_idempotency_keys"}
                emit(json.dumps(report, sort_keys=True))
                return 2
            except PortalFailure as failure:
                entry["last_http_status"] = failure.status
                private_replace(journal_path, journal)
                emit(json.dumps({"event": "order_submission_stopped",
                                 "run_id": journal["run_id"],
                                 "reason": failure.code,
                                 "next": "inspect_portal_then_resume_same_journal"},
                                sort_keys=True))
                return 2
            entry["last_http_status"] = status
            entry["order_id"] = order_id
            entry["state"] = state
            entry["replayed"] = replayed
            private_replace(journal_path, journal)

        if stopped_at_window and any(e["order_id"] is None for e in journal["orders"]):
            emit(json.dumps({"event": "send_window_reached",
                             "run_id": journal["run_id"],
                             "known_orders": sum(e["order_id"] is not None for e in journal["orders"]),
                             "requested_orders": journal["count"],
                             "next": "resume_same_journal"}, sort_keys=True))
            return 2

        observe = journal["observe_seconds"]
        order_ids = {entry["order_id"]: entry for entry in journal["orders"]
                     if entry["order_id"] is not None}
        observation_error = None
        if observe and order_ids:
            deadline = clock() + observe
            max_pages = min(8, math.ceil(len(order_ids) / 20) + 2)
            while clock() < deadline:
                cursor = None
                visited = set()
                found = {}
                try:
                    for page_number in range(max_pages):
                        remaining = deadline - clock()
                        if remaining <= 0:
                            break
                        items, next_cursor = client.orders_page(
                            cursor, timeout=min(HTTP_TIMEOUT_SECONDS, max(0.1, remaining)))
                        for item in items:
                            candidate_id = item.get("order_id") if isinstance(item, dict) else None
                            if isinstance(candidate_id, str) and candidate_id in order_ids:
                                state = item.get("state")
                                if state in ("accepted", "confirmed", "rejected"):
                                    found[candidate_id] = state
                        if next_cursor is None:
                            break
                        if next_cursor in visited:
                            raise PortalFailure("order_cursor_cycle")
                        visited.add(next_cursor)
                        cursor = next_cursor
                        if page_number + 1 < max_pages and clock() < deadline:
                            sleep_fn(min(1.0, max(0.0, deadline - clock())))
                except (PortalFailure, OutcomeUnknown) as failure:
                    observation_error = failure.code
                    break
                changed = False
                for order_id, state in found.items():
                    entry = order_ids[order_id]
                    if entry["state"] != state:
                        entry["state"] = state
                        changed = True
                if changed:
                    private_replace(journal_path, journal)
                if len(found) == len(order_ids) and all(
                        state in ("confirmed", "rejected") for state in found.values()):
                    break
                remaining = deadline - clock()
                if remaining > 0:
                    sleep_fn(min(5.0, remaining))

        stock_error = None
        try:
            journal["stock_after"] = client.catalog_available(journal["sku"])
            private_replace(journal_path, journal)
        except PortalFailure as failure:
            stock_error = failure.code
        states = {}
        for entry in journal["orders"]:
            key = entry["state"] or "unknown"
            states[key] = states.get(key, 0) + 1
        terminal = sum(entry["state"] in ("confirmed", "rejected")
                       for entry in journal["orders"])
        summary = {
            "event": "workload_observed",
            "run_id": journal["run_id"],
            "requested_orders": journal["count"],
            "known_order_ids": len(order_ids),
            "sku": journal["sku"],
            "stock_before": journal["stock_before"],
            "stock_after": journal["stock_after"],
            "stock_decrease": (journal["stock_before"] - journal["stock_after"]
                               if journal["stock_before"] is not None
                               and journal["stock_after"] is not None else None),
            "http_202": sum(e["last_http_status"] == 202 for e in journal["orders"]),
            "http_200_replay": sum(e["last_http_status"] == 200 for e in journal["orders"]),
            "terminal_orders": terminal,
            "states": states,
            "duration_seconds": round(max(0.0, clock() - started), 2),
            "journal": str(journal_path),
            "observation_error": observation_error,
            "orders": [{"order_id": e["order_id"], "state": e["state"],
                        "http_status": e["last_http_status"], "replayed": e["replayed"]}
                       for e in journal["orders"]],
        }
        emit(json.dumps(summary, sort_keys=True))
        if stock_error or (observe and observation_error):
            return 2
        if any(e["order_id"] is None for e in journal["orders"]):
            return 2
        if observe and terminal != journal["count"]:
            return 2
        return 0
    except SafeFailure as failure:
        emit(json.dumps({"event": "workload_stopped", "reason": failure.code},
                        sort_keys=True))
        return 2
    except OSError:
        emit(json.dumps({"event": "workload_stopped", "reason": "local_file_error"},
                        sort_keys=True))
        return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portal", required=True, help="Cloud Run lab007-portal HTTPS URL")
    parser.add_argument("--demo-logins", required=True, help="Private demo-logins.json from the Lab bundle")
    parser.add_argument("--journal", required=True, help="Private run journal; never delete while outcome is unknown")
    parser.add_argument("--customer", choices=("alice", "bob"))
    parser.add_argument("--count", type=int)
    parser.add_argument("--sku")
    parser.add_argument("--quantity", type=int)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--observe-seconds", type=int)
    parser.add_argument("--resume", action="store_true")
    return execute(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
