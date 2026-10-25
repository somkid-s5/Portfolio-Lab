"""Inspect booking invariants and connection counts; optionally retire drained login A."""
import argparse
import json
from pathlib import Path
import sys
from sqlalchemy import text
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'app' if (BASE/'app').is_dir() else BASE))
from database import create_pool

def snapshot(engine):
    with engine.connect() as conn:
        violations=[dict(r) for r in conn.exec_driver_sql((BASE/'db/check-invariants.sql').read_text()).mappings()]
        slots=[dict(r) for r in conn.execute(text('SELECT id,label,capacity,booked FROM slots ORDER BY id')).mappings()]
        counts=[dict(r) for r in conn.execute(text('SELECT usename,state,count(*) AS connections FROM pg_stat_activity WHERE datname=current_database() GROUP BY usename,state ORDER BY usename,state')).mappings()]
        roles=[dict(r) for r in conn.execute(text("SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname IN ('booking_a','booking_b') ORDER BY rolname")).mappings()]
        return {'invariant_violations':violations,'slots':slots,'connections':counts,'roles':roles}

def retire_a(engine):
    # NOLOGIN does not kill an existing connection. Never claim that it does.
    # Serialize administrative invocations; caller must first remove A traffic/tags/revisions.
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(4004,1)"))
        roles=dict(conn.execute(text("SELECT rolname,rolcanlogin FROM pg_roles WHERE rolname IN ('booking_a','booking_b')")).all())
        if not roles.get('booking_b'):
            raise ValueError('Login B must exist and allow login before retiring A')
        if 'booking_a' not in roles:
            raise ValueError('Expected dedicated booking_a login')
        count=conn.execute(text("SELECT count(*) FROM pg_stat_activity WHERE usename='booking_a'")).scalar_one()
        if count:
            raise ValueError('A still has connections; remove its traffic/tags/revisions and wait, do not force-terminate')
        conn.exec_driver_sql('ALTER ROLE booking_a NOLOGIN')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--retire-a',action='store_true')
    p.add_argument('--confirm-drained',action='store_true',
                   help='Assert A has no traffic, tags, live revisions or jobs; then check connections')
    args=p.parse_args()
    if args.retire_a and not args.confirm_drained:
        p.error('--retire-a requires --confirm-drained; never retire a live revision login')
    engine=create_pool()
    try:
        if args.retire_a:
            retire_a(engine)
        result=snapshot(engine)
        print(json.dumps(result,default=str,sort_keys=True))
        if result['invariant_violations']:
            raise SystemExit(2)
    finally:
        engine.dispose()
if __name__=='__main__':
    main()
