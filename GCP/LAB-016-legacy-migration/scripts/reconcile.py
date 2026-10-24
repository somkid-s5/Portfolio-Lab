from __future__ import annotations
import json
import os
import sys
import time
import psycopg

def connect(prefix: str):
    return psycopg.connect(
        host=os.environ[f"{prefix}_HOST"], port=int(os.getenv(f"{prefix}_PORT", "5432")),
        dbname=os.environ[f"{prefix}_DATABASE"], user=os.environ[f"{prefix}_USER"],
        password=os.environ[f"{prefix}_PASSWORD"], connect_timeout=5,
        sslmode=os.getenv(f"{prefix}_SSLMODE", "prefer"),
        application_name="lab016-reconcile",
    )

def snapshot(conn) -> dict:
    count, total, maximum = conn.execute(
        "SELECT count(*)::bigint, COALESCE(sum(amount_cents),0)::bigint, "
        "COALESCE(max(id),0)::bigint FROM public.orders"
    ).fetchone()
    statuses = conn.execute(
        "SELECT status,count(*)::bigint FROM public.orders GROUP BY status ORDER BY status"
    ).fetchall()
    sequence = conn.execute(
        "SELECT last_value,is_called FROM public.orders_id_seq"
    ).fetchone()
    refs = conn.execute(
        "SELECT count(DISTINCT order_ref)::bigint FROM public.orders"
    ).fetchone()[0]
    return {"count": count, "total_amount_cents": total, "max_id": maximum,
            "distinct_order_refs": refs, "by_status": {k: v for k, v in statuses},
            "sequence_last_value": sequence[0], "sequence_is_called": sequence[1]}

def compare(source: dict, target: dict) -> dict:
    keys=("count","total_amount_cents","max_id","distinct_order_refs","by_status",
          "sequence_last_value","sequence_is_called")
    return {key: source[key] == target[key] for key in keys}

def main() -> int:
    started=time.monotonic()
    with connect("SOURCE") as src, connect("TARGET") as dst:
        source=snapshot(src); target=snapshot(dst)
    checks=compare(source,target)
    result={"source":source,"target":target,"checks":checks,"match":all(checks.values()),
            "duration_seconds":round(time.monotonic()-started,3),
            "note":"Synthetic-data reconciliation only; review every mismatch before cutover."}
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result["match"] else 2
if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (KeyError,ValueError) as exc:
        print(json.dumps({"error":"missing_or_invalid_connection_setting","setting":str(exc)}),file=sys.stderr)
        raise SystemExit(64)
    except psycopg.Error as exc:
        print(json.dumps({"error":"database_connection_or_query_failed","error_type":type(exc).__name__}),file=sys.stderr)
        raise SystemExit(1)
