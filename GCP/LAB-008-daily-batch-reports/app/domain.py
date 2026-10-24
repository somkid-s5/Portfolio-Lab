"""Deterministic validation and aggregation for Daily Sales Close."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import io
import json
import re
from zoneinfo import ZoneInfo

MAX_INPUT_BYTES = 5 * 1024 * 1024
MAX_DATA_ROWS = 5_000
MAX_QUANTITY = 1_000
MAX_UNIT_PRICE_MINOR = 100_000_000
BUSINESS_TZ = ZoneInfo("Asia/Bangkok")
COLUMNS = ("transaction_id", "sold_at", "sku", "quantity", "unit_price_minor", "currency")
TXN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")
RFC3339_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
INTEGER_RE = re.compile(r"^[0-9]+$")


class InputError(ValueError):
    """Safe validation failure; never includes raw CSV values."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DailyReport:
    business_date: str
    source_generation: str
    source_sha256: str
    report_id: str
    canonical_json: bytes


def _fail(code: str) -> None:
    raise InputError(code)


def _business_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        _fail("INVALID_BUSINESS_DATE")
    if parsed.isoformat() != value:
        _fail("INVALID_BUSINESS_DATE")
    return parsed


def _integer(value: str | None, *, minimum: int, maximum: int, code: str) -> int:
    if value is None or not INTEGER_RE.fullmatch(value):
        _fail(code)
    number = int(value)
    if not minimum <= number <= maximum:
        _fail(code)
    return number


def build_report(csv_bytes: bytes, *, business_date: str, source_generation: str) -> DailyReport:
    """Validate pinned source bytes and build a deterministic, source-bound report."""
    target_date = _business_date(business_date)
    if not isinstance(source_generation, str) or not INTEGER_RE.fullmatch(source_generation):
        _fail("INVALID_SOURCE_GENERATION")
    if int(source_generation) <= 0:
        _fail("INVALID_SOURCE_GENERATION")
    if not isinstance(csv_bytes, bytes):
        _fail("INVALID_INPUT_BYTES")
    if len(csv_bytes) > MAX_INPUT_BYTES:
        _fail("INPUT_TOO_LARGE")

    source_sha256 = hashlib.sha256(csv_bytes).hexdigest()
    try:
        text = csv_bytes.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        _fail("INVALID_UTF8")

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            _fail("INVALID_HEADER")
        by_sku: dict[str, dict[str, int]] = {}
        transaction_ids: set[str] = set()
        row_count = total_quantity = total_amount_minor = 0
        for row in reader:
            if row_count >= MAX_DATA_ROWS:
                _fail("TOO_MANY_ROWS")
            if None in row or any(value is None or value == "" for value in row.values()):
                _fail("INVALID_ROW_SHAPE")
            tx_id = row["transaction_id"]
            if not TXN_RE.fullmatch(tx_id):
                _fail("INVALID_TRANSACTION_ID")
            if tx_id in transaction_ids:
                _fail("DUPLICATE_TRANSACTION_ID")
            transaction_ids.add(tx_id)

            if not RFC3339_TIMESTAMP.fullmatch(row["sold_at"]):
                _fail("INVALID_TIMESTAMP")
            try:
                sold_at = datetime.fromisoformat(row["sold_at"].replace("Z", "+00:00"))
            except ValueError:
                _fail("INVALID_TIMESTAMP")
            if sold_at.tzinfo is None or sold_at.utcoffset() is None:
                _fail("TIMEZONE_REQUIRED")
            if sold_at.astimezone(BUSINESS_TZ).date() != target_date:
                _fail("BUSINESS_DATE_MISMATCH")

            sku = row["sku"]
            if not SKU_RE.fullmatch(sku):
                _fail("INVALID_SKU")
            quantity = _integer(row["quantity"], minimum=1, maximum=MAX_QUANTITY,
                                code="INVALID_QUANTITY")
            unit_price = _integer(row["unit_price_minor"], minimum=0,
                                  maximum=MAX_UNIT_PRICE_MINOR, code="INVALID_UNIT_PRICE")
            if row["currency"] != "THB":
                _fail("UNSUPPORTED_CURRENCY")

            amount = quantity * unit_price
            item = by_sku.setdefault(sku, {"row_count": 0, "quantity": 0,
                                           "amount_minor": 0})
            item["row_count"] += 1
            item["quantity"] += quantity
            item["amount_minor"] += amount
            row_count += 1
            total_quantity += quantity
            total_amount_minor += amount
    except csv.Error:
        _fail("MALFORMED_CSV")

    if row_count == 0:
        _fail("EMPTY_REPORT")
    identity = f"{business_date}\0{source_generation}\0{source_sha256}".encode("ascii")
    report_id = hashlib.sha256(identity).hexdigest()
    document = {
        "schema_version": 1,
        "report_id": report_id,
        "business_date": business_date,
        "currency": "THB",
        "source": {"generation": source_generation, "sha256": source_sha256},
        "row_count": row_count,
        "total_quantity": total_quantity,
        "total_amount_minor": total_amount_minor,
        "by_sku": [{"sku": sku, **by_sku[sku]} for sku in sorted(by_sku)],
    }
    canonical = (json.dumps(document, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")) + "\n").encode("utf-8")
    return DailyReport(business_date, source_generation, source_sha256,
                       report_id, canonical)
