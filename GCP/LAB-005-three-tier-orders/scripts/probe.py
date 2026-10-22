"""Bounded read-only HTTP evidence probe; never logs cookies, CSRF or response bodies."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
import math
import re
import time
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler,ProxyHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def endpoint(base,path,local_test=False):
    value=urlsplit(base)
    if (value.username or value.password or value.query or value.fragment or value.path not in ('','/') or
        not value.hostname or path not in ('/livez','/healthz','/api/session')):
        raise ValueError('Expected origin only and an allowed read-only path')
    if local_test:
        if value.scheme!='http' or value.hostname not in ('127.0.0.1','localhost'):
            raise ValueError('Local test permits loopback HTTP only')
    elif value.scheme!='https' or value.port not in (None,443):
        raise ValueError('Public probe requires verified HTTPS on port443')
    return base.rstrip('/')+path

def safe_label(value):
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value) else None

def sample(url,timeout=5):
    started=time.monotonic()
    record={'time_utc':datetime.now(timezone.utc).isoformat(),'status':None}
    opener=build_opener(ProxyHandler({}),NoRedirect())
    try:
        request=Request(url,headers={'Accept':'application/json','Connection':'close','User-Agent':'Portfolio-Lab005-Probe/1'})
        try:
            response=opener.open(request,timeout=timeout)
        except HTTPError as exc:
            response=exc
        with response:
            record['status']=response.code
            record['web']=safe_label(response.headers.get('X-Web-ID'))
            record['api']=safe_label(response.headers.get('X-Backend-ID'))
            record['request_id']=safe_label(response.headers.get('X-Request-ID'))
            data=response.read(65537)
        if len(data)>65536:
            record['error']='response_too_large'
        else:
            try:
                payload=json.loads(data)
                if isinstance(payload,dict):
                    record['version']=safe_label(payload.get('version'))
                    record['api']=record['api'] or safe_label(payload.get('backend'))
            except (ValueError,UnicodeError):
                record['error']='invalid_json'
        if record['status']!=200:
            record.setdefault('error','unexpected_http_status')
    except (OSError,URLError,ValueError):
        record['error']='transport_or_tls_error'
    record['latency_ms']=round((time.monotonic()-started)*1000,2)
    return record

def run(url,count=20,workers=1,interval=1.0,emit=None):
    if type(count) is not int or not 1<=count<=200 or type(workers) is not int or not 1<=workers<=8 or not 0.1<=interval<=5:
        raise ValueError('Bounds: requests1..200 workers1..8 interval0.1..5seconds')
    records=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        remaining=count
        while remaining:
            batch=min(remaining,workers)
            results=list(pool.map(sample,[url]*batch))
            records.extend(results)
            if emit:
                for record in results:
                    emit({'event':'sample',**record})
            remaining-=batch
            if remaining:
                time.sleep(interval)
    latency=sorted(record['latency_ms'] for record in records)
    summary={'event':'summary','requests':len(records),'errors':sum('error' in r for r in records),
             'status_counts':dict(Counter(str(r['status']) for r in records)),
             'web_counts':dict(Counter(r.get('web') for r in records if r.get('web'))),
             'api_counts':dict(Counter(r.get('api') for r in records if r.get('api'))),
             'version_counts':dict(Counter(r.get('version') for r in records if r.get('version'))),
             'p95_ms':latency[math.ceil(len(latency)*0.95)-1],
             'interpretation':'Observed samples only; not an SLA, capacity guarantee or proof of equal distribution.'}
    if emit:
        emit(summary)
    return summary

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--path',choices=['/livez','/healthz','/api/session'],default='/healthz')
    parser.add_argument('--requests',type=int,default=20)
    parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--interval',type=float,default=1.0)
    parser.add_argument('--local-test',action='store_true',help='CI loopback HTTP only; never disables HTTPS verification')
    args=parser.parse_args()
    try:
        url=endpoint(args.base_url,args.path,args.local_test)
        result=run(url,args.requests,args.workers,args.interval,
                   emit=lambda value:print(json.dumps(value,sort_keys=True),flush=True))
        return 3 if result['errors'] else 0
    except ValueError:
        print(json.dumps({'event':'invalid_probe_configuration'}))
        return 2

if __name__=='__main__':
    raise SystemExit(main())
