"""Read-only consistent snapshot of Orders invariants. No credentials or customer data output."""
import json
from pathlib import Path
import sys
from sqlalchemy import text

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from database import create_pool

def inspect(engine):
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with conn.begin():
            conn.exec_driver_sql('SET TRANSACTION READ ONLY')
            identity=conn.execute(text('SELECT current_user AS db_role,current_database() AS database,now()::text AS observed_at')).mappings().one()
            stock=[dict(row) for row in conn.execute(text(
                'SELECT sku,initial_stock,available FROM products ORDER BY sku LIMIT 100')).mappings()]
            counts=dict(conn.execute(text(
                "SELECT (SELECT count(*) FROM products) AS products,(SELECT count(*) FROM orders) AS orders,"
                "(SELECT count(*) FROM order_items) AS items,(SELECT count(*) FROM stock_events) AS ledger_events,"
                "(SELECT count(*) FROM orders WHERE status='confirmed') AS confirmed,"
                "(SELECT count(*) FROM orders WHERE status='cancelled') AS cancelled")).mappings().one())
            source=(ROOT/'db/check-invariants.sql').read_text().strip().rstrip(';')
            violations=[dict(row) for row in conn.execute(text('SELECT * FROM ('+source+') AS violations LIMIT 1001')).mappings()]
            connections=dict(conn.execute(text(
                'SELECT count(*) AS role_connections,count(*) FILTER (WHERE state=\'active\') AS active '
                'FROM pg_stat_activity WHERE usename=current_user')).mappings().one())
    return {'event':'orders_snapshot',**dict(identity),'counts':counts,'stock':stock,
            'violations':violations[:1000],'violations_truncated':len(violations)>1000,
            'invariants_ok':not violations,'connections':connections,
            'scope':'Single read-only snapshot; connection count includes this inspector. Not failover verification.'}

def main():
    engine=None
    try:
        engine=create_pool()
        result=inspect(engine)
        print(json.dumps(result,sort_keys=True))
        return 0 if result['invariants_ok'] else 3
    except Exception as exc:
        print(json.dumps({'event':'inspection_failed','error_type':type(exc).__name__}),file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()

if __name__=='__main__':
    raise SystemExit(main())
