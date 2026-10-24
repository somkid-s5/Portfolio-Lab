"""Bounded CSV domain processing. No storage, credentials, HTTP or file writes."""
import csv
import hashlib
import io
import json
import re

HEADER = ["sale_id", "sku", "quantity", "unit_price_satang"]
MAX_INTEGER = 2**63 - 1


class Rejected(ValueError):
    """Safe reason code only; never include file contents in errors."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical_bytes(summary):
    return json.dumps(summary, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def bounded_read(stream, max_bytes):
    if type(max_bytes) is not int or not 1 <= max_bytes <= 5 * 1024 * 1024:
        raise ValueError("invalid_max_bytes")
    chunks, size = [], 0
    while size <= max_bytes:
        chunk = stream.read(min(65536, max_bytes + 1 - size))
        if not isinstance(chunk, bytes):
            raise TypeError("binary_stream_required")
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > max_bytes:
            raise Rejected("file_too_large")
        chunks.append(chunk)
    raise Rejected("file_too_large")


def _integer(value, minimum, maximum):
    if not re.fullmatch(r"0|[1-9][0-9]{0,15}", value):
        raise Rejected("invalid_integer")
    number = int(value)
    if not minimum <= number <= maximum:
        raise Rejected("integer_out_of_range")
    return number


def summarize(data, *, max_bytes=1048576, max_rows=10000, processor_version="v1"):
    if (type(max_bytes) is not int or not 1 <= max_bytes <= 5242880 or
            type(max_rows) is not int or not 1 <= max_rows <= 50000 or
            not isinstance(processor_version, str) or
            not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", processor_version)):
        raise ValueError("invalid_processing_contract")
    if not isinstance(data, bytes):
        raise TypeError("bytes_required")
    if len(data) > max_bytes:
        raise Rejected("file_too_large")
    if not data:
        raise Rejected("empty_file")
    try:
        # Accept one leading UTF-8 BOM and CRLF. Hash remains over original bytes.
        content = data.decode("utf-8-sig")
    except UnicodeError:
        raise Rejected("invalid_utf8") from None
    if "\x00" in content:
        raise Rejected("null_byte")
    reader = csv.reader(io.StringIO(content, newline=""), strict=True)
    seen, groups, rows, units, total = set(), {}, 0, 0, 0
    try:
        header = next(reader, None)
        if header != HEADER or reader.line_num != 1:
            raise Rejected("invalid_header")
        previous_line = reader.line_num
        for fields in reader:
            # No embedded newlines or blank records; LF and CRLF are accepted.
            if reader.line_num != previous_line + 1:
                raise Rejected("multiline_record")
            previous_line = reader.line_num
            if len(fields) != 4:
                raise Rejected("invalid_columns")
            if any(len(field) > 128 for field in fields):
                raise Rejected("field_too_long")
            rows += 1
            if rows > max_rows:
                raise Rejected("too_many_rows")
            sale_id, sku, quantity, price = fields
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", sale_id):
                raise Rejected("invalid_sale_id")
            if sale_id in seen:
                raise Rejected("duplicate_sale_id")
            seen.add(sale_id)
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,31}", sku):
                raise Rejected("invalid_sku")
            quantity = _integer(quantity, 1, 1000000)
            price = _integer(price, 0, 100000000)
            amount = quantity * price
            units += quantity
            total += amount
            if total > MAX_INTEGER or units > MAX_INTEGER:
                raise Rejected("total_overflow")
            group = groups.setdefault(sku, {"sku": sku, "rows": 0, "units": 0,
                                            "total_satang": 0})
            group["rows"] += 1
            group["units"] += quantity
            group["total_satang"] += amount
    except csv.Error:
        raise Rejected("malformed_csv") from None
    if rows == 0:
        raise Rejected("no_data_rows")
    return {"schema_version": 1, "processor_version": processor_version,
            "input_sha256": hashlib.sha256(data).hexdigest(),
            "rows": rows, "units": units, "total_satang": total,
            "by_sku": [groups[key] for key in sorted(groups)]}
