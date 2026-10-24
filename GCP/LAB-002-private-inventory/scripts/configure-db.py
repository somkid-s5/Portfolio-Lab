"""Configure the dedicated Debian 12/PostgreSQL 15 lab DB VM. Root only."""
import argparse
import os
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def sql(command, database='postgres'):
    result=subprocess.run(['runuser','-u','postgres','--','psql','-X',
         '-v','ON_ERROR_STOP=1','-At','-d',database], input=command,
         text=True,capture_output=True,check=False)
    if result.returncode:
        # SQL input may contain a password: never include it or stderr in output.
        raise RuntimeError('Database setup failed. Inspect DB service locally; SQL input redacted.')
    return result.stdout.strip()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--password-file',required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:
        parser.error('Run with sudo on dedicated DB VM only')
    password=Path(args.password_file).read_text().strip()
    if not re.fullmatch('[A-Za-z0-9_-]{32,100}',password):
        parser.error('Use generated URL-safe password, 32–100 characters')
    if sql("SHOW server_version_num;")[:2]!='15':
        raise RuntimeError('This installer targets PostgreSQL 15 only')
    sql("SET password_encryption='scram-sha-256'; DO $$ BEGIN IF NOT EXISTS "
        "(SELECT FROM pg_roles WHERE rolname='inventory_app') THEN "
        "CREATE ROLE inventory_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE; "
        "END IF; END $$; ALTER ROLE inventory_app PASSWORD '"+password+"';")
    if sql("SELECT 1 FROM pg_database WHERE datname='inventory';")!='1':
        sql("CREATE DATABASE inventory;")
    for filename in ['schema.sql','seed.sql','grants.sql']:
        sql((ROOT/'db'/filename).read_text(),'inventory')
    sql("ALTER SYSTEM SET listen_addresses='localhost,10.22.20.10';")
    hba=Path(sql('SHOW hba_file;'))
    lines=hba.read_text().splitlines()
    marker='# LAB002 managed app access'
    if marker not in lines:
        hba.write_text(marker+'\nhost inventory inventory_app 10.22.10.0/24 scram-sha-256\n'
                       +'\n'.join(lines)+'\n')
    subprocess.run(['systemctl','restart','postgresql@15-main'],check=True)
    print('Database configured; schema and seed preserve existing movements. Password not printed.')

if __name__=='__main__':
    main()
