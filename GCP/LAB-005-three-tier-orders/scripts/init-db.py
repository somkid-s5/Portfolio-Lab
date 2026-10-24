"""One-time Orders bootstrap. A failure never prints SQL or secret-bearing errors."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from sqlalchemy import text

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'app'))
from database import create_pool

class BootstrapError(Exception):
    def __init__(self,code):
        self.code=code

def initialize(engine,runtime):
    if runtime.get('user')!='orders_app' or runtime.get('database')!='orders' or not re.fullmatch(r'[A-Za-z0-9_-]{32,100}',runtime.get('password','')):
        raise BootstrapError('invalid_runtime_bundle')
    with engine.begin() as conn:
        if tuple(conn.execute(text('SELECT current_user,current_database()')).one())!=('postgres','orders'):
            raise BootstrapError('wrong_admin_or_database')
        if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname='orders_app'")).first():
            raise BootstrapError('runtime_role_exists')
        conn.exec_driver_sql("CREATE ROLE orders_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '"+runtime['password']+"'")
        for filename in ['schema.sql','seed.sql','grants.sql']:
            for statement in (BASE/'db'/filename).read_text().split(';'):
                if statement.strip():
                    conn.exec_driver_sql(statement)
        violations=conn.exec_driver_sql((BASE/'db/check-invariants.sql').read_text()).all()
        if violations:
            raise BootstrapError('seed_invariant_failure')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-file',required=True)
    args=p.parse_args()
    engine=None
    try:
        runtime=json.loads(Path(args.runtime_file).read_text())
        admin=json.loads(Path(os.environ['DB_CONFIG_FILE']).read_text())
        if admin.get('database')!='orders' or admin.get('user')!='postgres':
            raise BootstrapError('wrong_admin_config')
        engine=create_pool()
        initialize(engine,runtime)
        print('Schema, seed and least-privilege orders_app created atomically. No passwords printed.')
        return 0
    except BootstrapError as exc:
        print('Bootstrap stopped: '+exc.code,file=sys.stderr)
        return 2
    except Exception as exc:
        # CREATE ROLE uses a validated literal; a DB exception can retain that SQL.
        # Do not print str(exc), repr(exc), a chained traceback or connection config.
        print('Bootstrap failed: '+type(exc).__name__+'; inspect identity/network/schema without exposing secrets.',file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()
if __name__=='__main__':
    raise SystemExit(main())
