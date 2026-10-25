"""Six bounded concurrent stock requests. Keep journal until results and DB evidence are complete."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import threading
import uuid
from journey import Client,origin,private_json

def state(path):
    path=Path(path)
    if path.exists() or path.is_symlink():
        value=private_json(path)
    else:
        value={'schema':1,'keys':['race-'+uuid.uuid4().hex for _ in range(6)],
               'items':[{'sku':'USB-01','quantity':1}]}
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as handle:
            json.dump(value,handle)
            handle.flush()
            os.fsync(handle.fileno())
    if (not isinstance(value,dict) or set(value)!={'schema','keys','items'} or value['schema']!=1 or
        not isinstance(value['keys'],list) or len(value['keys'])!=6 or len(set(value['keys']))!=6 or
        any(not isinstance(k,str) or len(k)!=37 or not k.startswith('race-') or
            any(c not in '0123456789abcdef' for c in k[5:]) for k in value['keys']) or
        value['items']!=[{'sku':'USB-01','quantity':1}]):
        raise ValueError('Unexpected race journal')
    return value

def race(base,logins,journal):
    barrier=threading.Barrier(6,timeout=20)
    def worker(key):
        client=Client(base)
        client.login('alice',logins['alice'])
        barrier.wait()
        status,result=client.request('POST','/api/orders',{'items':journal['items']},key)
        if status in (200,201):
            order=result.get('order',{})
            reference=str(uuid.UUID(order['id']))
            if order.get('status')!='confirmed':
                raise ValueError('Do not rerun a race after cancellation')
            return {'outcome':'confirmed','order_id':reference,'replayed':result.get('replayed') is True}
        if status==409 and result.get('error')=='insufficient_stock':
            return {'outcome':'insufficient_stock'}
        raise ValueError('Unexpected request outcome; retain journal')
    with ThreadPoolExecutor(max_workers=6) as executor:
        rows=list(executor.map(worker,journal['keys']))
    references=[row['order_id'] for row in rows if row['outcome']=='confirmed']
    if len(references)!=len(set(references)):
        raise ValueError('Distinct logical orders unexpectedly share a reference')
    return {'event':'stock_race','attempts':6,'confirmed':len(references),
            'rejected':sum(r['outcome']=='insufficient_stock' for r in rows),'results':rows,
            'scope':'Compare starting stock and DB ledger. Expected4/2 only for clean USB stock4 and no other writers.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--logins-file',required=True)
    parser.add_argument('--journal',required=True)
    parser.add_argument('--local-test',action='store_true')
    args=parser.parse_args()
    try:
        base=origin(args.base_url,args.local_test)
        logins=private_json(args.logins_file)
        journal_path=Path(args.journal)
        journal=state(journal_path)
        result_path=journal_path.with_name(journal_path.name+'.result.json')
        if result_path.exists() or result_path.is_symlink():
            # A terminal snapshot is immutable: never resend rejected keys after stock is returned.
            print(json.dumps({'event':'stored_race_result','result':private_json(result_path),
                              'network_requests':0},sort_keys=True))
            return 0
        result=race(base,logins,journal)
        with os.fdopen(os.open(result_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as handle:
            json.dump(result,handle)
            handle.flush()
            os.fsync(handle.fileno())
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({'event':'race_failed','error_type':type(exc).__name__,
                          'next':'Retain journal; do not cancel any order or reset stock before resolving all outcomes.'}),file=sys.stderr)
        return 2
if __name__=='__main__':
    raise SystemExit(main())
