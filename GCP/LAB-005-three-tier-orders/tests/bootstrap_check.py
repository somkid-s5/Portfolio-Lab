"""Run only against the fresh GitHub Actions PostgreSQL fixture, before App tests."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from sqlalchemy import create_engine,text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

ROOT=Path(__file__).resolve().parents[1]

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('PGHOST')!='127.0.0.1' or os.environ.get('PGDATABASE')!='orders_ci' or os.environ.get('PGUSER')!='postgres':
        raise RuntimeError('This check requires the dedicated cloud CI localhost PostgreSQL service')
    def pool(database,user,password):
        return create_engine(URL.create('postgresql+pg8000',username=user,password=password,
            host='127.0.0.1',port=5432,database=database),hide_parameters=True,connect_args={'timeout':5})
    control=pool('orders_ci','postgres',os.environ['PGPASSWORD'])
    admin=None
    runtime=None
    owned=False
    try:
        with control.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            if conn.execute(text("SELECT 1 FROM pg_database WHERE datname='orders'")).first() or conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname='orders_app'")).first():
                raise RuntimeError('Fresh fixture expected; refusing to alter any pre-existing database or role')
            conn.exec_driver_sql('CREATE DATABASE orders')
            owned=True
        admin=pool('orders','postgres',os.environ['PGPASSWORD'])
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)
            bundle=work/'secrets'
            result=subprocess.run([sys.executable,str(ROOT/'scripts/create-secrets.py'),'--out',str(bundle)],
                                  capture_output=True,text=True,timeout=20)
            assert result.returncode==0,'Secret generator failed; values intentionally withheld'
            config=json.loads((bundle/'db.json').read_text())
            admin_file=work/'admin-ci.json'
            with admin_file.open('x') as handle:
                os.chmod(admin_file,0o600)
                json.dump({'database':'orders','user':'postgres','password':os.environ['PGPASSWORD'],'host':'127.0.0.1','port':5432},handle)
            environment=dict(os.environ,DB_MODE='local',DB_CONFIG_FILE=str(admin_file))
            def execute(runtime_file,expected):
                result=subprocess.run([sys.executable,str(ROOT/'scripts/init-db.py'),'--runtime-file',str(runtime_file)],
                                      capture_output=True,text=True,timeout=30,env=environment)
                assert result.returncode==expected,'Unexpected bootstrap exit; secret-bearing output intentionally withheld'
                current_password=json.loads(Path(runtime_file).read_text())['password']
                assert current_password not in result.stdout+result.stderr,'Candidate password was printed'
                assert config['password'] not in result.stdout+result.stderr,'Runtime password was printed'
                assert os.environ['PGPASSWORD'] not in result.stdout+result.stderr,'Admin password was printed'
                return result

            # Fail after CREATE ROLE; transaction must remove that role again.
            with admin.begin() as conn:
                conn.exec_driver_sql('CREATE TABLE products (fixture_only integer)')
            execute(bundle/'db.json',2)
            with admin.connect() as conn:
                assert not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname='orders_app'")).first(),'Failed bootstrap left a role behind'
                assert not conn.execute(text("SELECT 1 FROM information_schema.tables WHERE table_name='orders'")).first(),'Failed bootstrap left App tables'
            with admin.begin() as conn:
                conn.exec_driver_sql('DROP TABLE products')
            execute(bundle/'db.json',0)
            with admin.connect() as conn:
                assert conn.execute(text('SELECT count(*) FROM products')).scalar_one()==5
                assert conn.exec_driver_sql((ROOT/'db/check-invariants.sql').read_text()).all()==[]
                assert tuple(conn.execute(text("SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname='orders_app'")).one())==(False,False,False)
            runtime=pool('orders','orders_app',config['password'])
            with runtime.connect() as conn:
                assert conn.execute(text('SELECT count(*) FROM products')).scalar_one()==5
            changed=work/'changed-db.json'
            candidate=dict(config,password=secrets.token_urlsafe(32))
            changed.write_text(json.dumps(candidate))
            os.chmod(changed,0o600)
            result=execute(changed,2)
            assert 'runtime_role_exists' in result.stderr
            runtime.dispose()
            with runtime.connect() as conn:
                assert conn.execute(text('SELECT count(*) FROM products')).scalar_one()==5
            wrong=pool('orders','orders_app',candidate['password'])
            try:
                try:
                    with wrong.connect():
                        pass
                    raise AssertionError('Existing runtime password was replaced')
                except SQLAlchemyError:
                    pass
            finally:
                wrong.dispose()
        print('BOOTSTRAP_CI: failure rollback, real schema/seed/grants, runtime login and no-reset rerun verified. Not GCP provisioning.')
    finally:
        if runtime is not None:
            runtime.dispose()
        if admin is not None:
            admin.dispose()
        if owned:
            with control.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
                conn.exec_driver_sql('DROP DATABASE orders')
                conn.exec_driver_sql('DROP ROLE IF EXISTS orders_app')
        control.dispose()
if __name__=='__main__':
    main()
