"""Bounded content/header evidence probe. Does not infer CDN hits from latency."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True,help='HTTPS origin without path/query')
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--requests',type=int,default=10,help='1–30 index requests plus one per asset')
    parser.add_argument('--out',required=True)
    parser.add_argument('--allow-local-http',action='store_true',help='Loopback fixture tests only; never proves TLS')
    args=parser.parse_args()
    parsed=urlsplit(args.url)
    scheme_ok=parsed.scheme=='https' or (args.allow_local_http and parsed.scheme=='http'
                  and parsed.hostname in ('127.0.0.1','localhost','::1'))
    if (not scheme_ok or not parsed.hostname or parsed.username or parsed.password
        or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        parser.error('Use an HTTPS origin, without credentials/path/query')
    if not 1<=args.requests<=30:
        parser.error('requests must be 1–30')
    manifest=json.loads(Path(args.manifest).read_text())
    if manifest.get('schema')!=1 or manifest.get('release') not in ('v1','v2','bad'):
        parser.error('Unsupported manifest')
    files=manifest['files']
    if len(files)!=2 or not any(f.get('path')=='index.html' for f in files):
        parser.error('Expected index and asset')
    for f in files:
        if f['path'].startswith('/') or '..' in Path(f['path']).parts or '?' in f['path']:
            parser.error('Invalid manifest path')
    output=Path(args.out)
    output.parent.mkdir(parents=True,exist_ok=True)
    checks=[]
    rows=[]
    schedule=[next(f for f in files if f['path']=='index.html')]*args.requests
    schedule += [f for f in files if f['path']!='index.html']
    with output.open('x') as handle:
        next_request=time.monotonic()
        for f in schedule:
            delay=next_request-time.monotonic()
            if delay>0:
                time.sleep(delay)
            next_request=time.monotonic()+.2
            url=args.url.rstrip('/')+'/'+f['path']
            tick=time.monotonic()
            row={'started_utc':datetime.now(timezone.utc).isoformat(),'url':url,'status':0}
            try:
                request=Request(url,headers={'Connection':'close'})
                try:
                    response=build_opener(ProxyHandler({})).open(request,timeout=5)
                except HTTPError as exc:
                    response=exc
                with response:
                    body=response.read(1024*1024+1)
                    row.update(status=response.status,sha256=hashlib.sha256(body).hexdigest(),
                        headers={key:response.headers.get(key) for key in
                                 ['Cache-Control','Age','ETag','Content-Type','Via']})
                    match=response.status==200 and len(body)<=1024*1024 and row['sha256']==f['sha256']
                    cache_ok=response.headers.get('Cache-Control','').replace(' ','')==f['cache_control']
                    business_ok=(f['path']!='index.html' or b'<h2>Support guide</h2>' in body)
                    row.update(content_match=match,cache_policy_match=cache_ok,business_content_ok=business_ok)
                    checks.extend([match,cache_ok,business_ok])
            except Exception as exc:
                row['error']=type(exc).__name__
                checks.append(False)
            row['latency_ms']=round((time.monotonic()-tick)*1000,2)
            rows.append(row)
        result={'finished_utc':datetime.now(timezone.utc).isoformat(),'expected_release':manifest['release'],
                'all_checks_passed':all(checks),'tls_verified':parsed.scheme=='https',
                'results':rows,'note':'No cache-buster. Confirm cacheHit/cacheLookup/cacheFillBytes from LB logs separately. Browser cache is not tested.'}
        json.dump(result,handle,indent=2)
    print(json.dumps({'output':str(output),'all_checks_passed':all(checks),'requests':len(rows)}))
    return 0 if all(checks) else 1

if __name__=='__main__':
    raise SystemExit(main())
