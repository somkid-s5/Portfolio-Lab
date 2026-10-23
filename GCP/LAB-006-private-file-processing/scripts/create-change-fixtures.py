"""Generate deterministic bounded CSV fixtures in a NEW private directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path

HEADER = b"sale_id,sku,quantity,unit_price_satang\n"
SKU = "SKU-" + "A"*28


def exact_csv(size, rows):
    if type(rows) is not int or not 1 <= rows <= 50000:
        raise ValueError("invalid_rows")
    minimum = len(HEADER) + sum(len(f"S{i:05d},{SKU},1,100000000\n".encode())
                                for i in range(rows))
    remaining = size - minimum
    if type(size) is not int or not 0 <= remaining <= rows*58:
        raise ValueError("unrepresentable_exact_size")
    result = [HEADER]
    for index in range(rows):
        padding = min(58, remaining)
        remaining -= padding
        result.append(f"S{index:05d}{'A'*padding},{SKU},1,100000000\n".encode())
    output = b"".join(result)
    if len(output) != size:
        raise AssertionError("size_mismatch")
    return output


def row_csv(rows):
    if type(rows) is not int or not 1 <= rows <= 50001:
        raise ValueError("invalid_rows")
    return HEADER + b"".join(f"S{i},BOOK-01,1,100\n".encode() for i in range(rows))


def generate(destination):
    target = Path(destination)
    target.mkdir(mode=0o700)
    os.chmod(target, 0o700)
    fixtures = {
        "exact-1mib.csv": exact_csv(1048576, 10000),
        "byte-change.csv": HEADER + b"".join(
            f"S{i:05d}{'A'*58},{SKU},1,100000000\n".encode() for i in range(10000)),
        "row-change.csv": row_csv(10001),
        "exact-5mib.csv": exact_csv(5242880, 50000),
        "too-many-rows.csv": row_csv(50001),
        "too-large.csv": b"x"*5242881,
    }
    manifest = {}
    for name, data in fixtures.items():
        fd = os.open(target/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        manifest[name] = {"bytes":len(data), "sha256":hashlib.sha256(data).hexdigest()}
    fd = os.open(target/"manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(manifest, handle, sort_keys=True, indent=2)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        manifest = generate(args.out)
        print(json.dumps({"event":"change_fixtures_created", "files":manifest}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"event":"fixture_creation_failed", "error_type":type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
