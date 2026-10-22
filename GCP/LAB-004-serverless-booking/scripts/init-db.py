"""One-time bootstrap job in a NEW lab database. Refuses existing runtime logins."""
import argparse
import json
from pathlib import Path
import re
import sys
from sqlalchemy import text
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'app' if (BASE/'app').is_dir() else BASE))
from database import create_pool

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role-a-file',required=True)
    parser.add_argument('--role-b-file',required=True)
    args=parser.parse_args()
    credentials=[json.loads(Path(p).read_text()) for p in [args.role_a_file,args.role_b_file]]
    if [c.get('user') for c in credentials]!=['booking_a','booking_b']:
        raise ValueError('Expected the two dedicated booking_a/booking_b logins')
    for c in credentials:
        if c.get('database')!='booking' or not re.fullmatch('[A-Za-z0-9_-]{32,100}',c.get('password','')):
            raise ValueError('Use the generated sandbox DB bundle')
    root=Path(__file__).resolve().parents[1]
    engine=create_pool()
    try:
        with engine.begin() as conn:
            for c in credentials:
                if conn.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:name'),{'name':c['user']}).first():
                    raise ValueError('Runtime role exists; stop and inspect instead of resetting a live password')
                conn.exec_driver_sql("CREATE ROLE "+c['user']+" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '"+c['password']+"'")
            for filename in ['schema.sql','seed.sql','grants.sql']:
                for statement in (root/'db'/filename).read_text().split(';'):
                    if statement.strip():
                        conn.exec_driver_sql(statement)
        print('Schema, seed and least-privilege logins created atomically. No passwords printed.')
    finally:
        engine.dispose()

def run():
    try:
        main()
        return 0
    except Exception as exc:
        # SQL exceptions can retain CREATE ROLE statements containing passwords.
        # Only our exact non-secret validation messages may be shown.
        safe_messages={
            'Expected the two dedicated booking_a/booking_b logins',
            'Use the generated sandbox DB bundle',
            'Runtime role exists; stop and inspect instead of resetting a live password'
        }
        if isinstance(exc,ValueError) and str(exc) in safe_messages:
            print(str(exc),file=sys.stderr)
        else:
            print('Bootstrap failed: '+type(exc).__name__+'; inspect configuration, IAM, networking and schema without exposing secrets.',file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(run())
