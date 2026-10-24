from __future__ import annotations
import argparse
import os
from pathlib import Path
import psycopg

ROOT = Path(__file__).resolve().parents[1]
def main() -> int:
    parser = argparse.ArgumentParser(description="Create or seed the Lab 16 Orders schema.")
    parser.add_argument("--seed", action="store_true", help="insert deterministic synthetic rows")
    args = parser.parse_args()
    conn = psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "orders"), user=os.getenv("DB_USER", "orders_app"),
        password=os.getenv("DB_PASSWORD", ""), connect_timeout=5,
    )
    try:
        conn.execute((ROOT / "app" / "schema.sql").read_text(encoding="utf-8"), prepare=False)
        if args.seed:
            conn.execute((ROOT / "app" / "seed.sql").read_text(encoding="utf-8"), prepare=False)
        conn.commit()
    finally:
        conn.close()
    print("schema=ready seed=" + ("loaded" if args.seed else "not-requested"))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
