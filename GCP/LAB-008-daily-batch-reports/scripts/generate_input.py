"""Create a fresh synthetic transaction CSV for one canonical business date."""
import argparse
import csv
from datetime import date
import hashlib
from pathlib import Path
import sys

COLUMNS = ("transaction_id", "sold_at", "sku", "quantity",
           "unit_price_minor", "currency")


def generate_input(business_date: str, output: str | Path) -> tuple[Path, str]:
    try:
        parsed = date.fromisoformat(business_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_business_date") from exc
    if parsed.isoformat() != business_date:
        raise ValueError("invalid_business_date")

    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    sold_at = f"{business_date}T09:00:00+07:00"
    amounts = (25_000, 24_000, 20_000, 10_000)
    rows = [
        (f"SALE-{parsed:%Y%m%d}-{number:03d}", sold_at, sku, "1", str(amount), "THB")
        for number, (sku, amount) in enumerate(
            zip(("COFFEE-01", "COFFEE-01", "MUG-01", "SPOON-01"), amounts),
            start=1,
        )
    ]

    with target.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return target, digest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Create four bounded, synthetic THB transaction rows.")
    parser.add_argument("--business-date", required=True,
                        help="Canonical YYYY-MM-DD business date.")
    parser.add_argument("--output", required=True,
                        help="New local output path; existing files are never overwritten.")
    args = parser.parse_args(argv)
    try:
        path, digest = generate_input(args.business_date, args.output)
    except (ValueError, FileExistsError, OSError):
        print("input_generation_failed: invalid_date_or_existing_unwritable_path",
              file=sys.stderr)
        return 2
    print(f"created={path} business_date={args.business_date} sha256={digest} rows=4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
