"""Bounded Inventory evidence collector. Synthetic sandbox data only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener
import uuid

def call(origin, path, token=None, data=None, key=None):
    headers={'Connection':'close'}
    if token:
        headers['Authorization']='Bearer '+token
    if key:
        headers['Idempotency-Key']=key
    raw=None if data is None else json.dumps(data).encode()
    tick=time.monotonic()
    request=Request(origin+path,data=raw,headers=headers)
    try:
        try:
            response=build_opener(ProxyHandler({})).open(request,timeout=5)
        except HTTPError as exc:
            response=exc
        with response:
            body=json.load(response)
            return {'status':response.status,'body':body,
                    'latency_ms':round((time.monotonic()-tick)*1000,2)}
    except Exception as exc:
        return {'status':0,'error':type(exc).__name__}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True,help='HTTP(S) origin, including :8080')
    parser.add_argument('--reader-file',required=True)
    parser.add_argument('--operator-file')
    parser.add_argument('--allow-writes',action='store_true')
    parser.add_argument('--requests',type=int,default=30)
    parser.add_argument('--out',required=True,help='New JSON filename only')
    args=parser.parse_args()
    parsed=urlsplit(args.url)
    if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username
        or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        parser.error('URL must be an HTTP(S) origin without credentials/path')
    if not 1<=args.requests<=100:
        parser.error('requests must be 1–100, at most 5/s')
    if args.allow_writes and not args.operator_file:
        parser.error('writes require --operator-file')
    reader=Path(args.reader_file).read_text().strip()
    operator=Path(args.operator_file).read_text().strip() if args.operator_file else None
    if not reader or (args.allow_writes and not operator):
        parser.error('Token files cannot be empty')
    origin=args.url.rstrip('/')
    results=[]
    checks=[]
    def collect(label,token=reader,data=None,key=None,path='/api/products?q=PEN-01'):
        result=call(origin,path,token,data,key)
        results.append({'label':label,**result})
        return result
    output=Path(args.out)
    output.parent.mkdir(parents=True,exist_ok=True)
    # Reserve before making changes: never overwrite previous evidence.
    with output.open('x') as handle:
        for i in range(args.requests):
            r=collect('read-'+str(i))
            checks.append(r['status']==200)
            if i+1<args.requests:
                time.sleep(.2)
        checks.append(collect('no-token',None)['status']==401)
        denied=collect('reader-write',reader,{'sku':'PEN-01','delta':-1},
                       'reader-'+uuid.uuid4().hex,path='/api/movements')
        checks.append(denied['status']==403)
        recovery='No write tests requested.'
        if args.allow_writes and all(checks):
            current=results[0]['body']['products'][0]['quantity']
            if not 1<=current<=1000:
                recovery='Skipped writes: sandbox stock must be 1–1000.'
                checks.append(False)
            else:
                prefix='probe-'+uuid.uuid4().hex
                movement={'sku':'PEN-01','delta':-1,'note':'bounded retry drill'}
                first=collect('withdraw',operator,movement,prefix,path='/api/movements')
                retry=collect('retry',operator,movement,prefix,path='/api/movements')
                checks.extend([first['status']==201,retry['status']==200,
                    first.get('body',{}).get('movement_id')==retry.get('body',{}).get('movement_id')])
                if first['status']==201:
                    restored=collect('restore-retry-drill',operator,
                        {'sku':'PEN-01','delta':1,'note':'restore retry drill'},prefix+'-restore',
                        path='/api/movements')
                    checks.append(restored['status']==201)
                # Re-read before the two concurrent withdrawals. No other users may write during this drill.
                state=collect('before-concurrency')
                if state['status']==200:
                    qty=state['body']['products'][0]['quantity']
                    amount=qty//2+1
                    if 1<=amount<=1000:
                        def withdraw(i):
                            return call(origin,'/api/movements',operator,
                                {'sku':'PEN-01','delta':-amount,'note':'concurrent drill'},prefix+'-c'+str(i))
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            concurrent=list(pool.map(withdraw,range(2)))
                        results.extend({'label':'concurrent-'+str(i),**r} for i,r in enumerate(concurrent))
                        checks.append(sorted(r['status'] for r in concurrent)==[201,409])
                        for i,r in enumerate(concurrent):
                            if r['status']==201:
                                restore=collect('restore-concurrent-'+str(i),operator,
                                    {'sku':'PEN-01','delta':amount,'note':'restore concurrent drill'},
                                    prefix+'-cr'+str(i),path='/api/movements')
                                checks.append(restore['status']==201)
                    else:
                        checks.append(False)
                else:
                    checks.append(False)
                final=collect('final-stock')
                checks.append(final['status']==200 and final['body']['products'][0]['quantity']==current)
                recovery=('If any request timed out, inspect movements and reconcile before retrying. '
                          'A client timeout does not prove that the transaction rolled back.')
        summary={'finished_utc':datetime.now(timezone.utc).isoformat(),
                 'url':origin,'read_requests':args.requests,'write_tests':args.allow_writes,
                 'all_checks_passed':all(checks),'results':results,'recovery_note':recovery,
                 'note':'Client evidence only, not a GCP capacity/security certification.'}
        json.dump(summary,handle,indent=2,ensure_ascii=False)
    print(json.dumps({'output':str(output),'all_checks_passed':all(checks),'requests_recorded':len(results)}))
    return 0 if all(checks) else 1

if __name__=='__main__':
    raise SystemExit(main())
