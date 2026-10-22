"""Bounded HTTPS booking journey/read probe. Never outputs cookies, CSRF or passwords."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
import json
from pathlib import Path
import secrets
import statistics
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPCookieProcessor,HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

class Client:
    def __init__(self,base,allow_loopback_http=False):
        u=urlsplit(base)
        loopback=u.hostname in ('127.0.0.1','localhost','::1')
        if u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
            raise ValueError('Use an origin URL only, without path, credentials, query or fragment')
        if u.scheme!='https' and not (allow_loopback_http and loopback and u.scheme=='http'):
            raise ValueError('HTTPS required; HTTP exception is loopback tests only')
        self.base=base.rstrip('/')
        self.opener=build_opener(NoRedirect(),HTTPCookieProcessor(CookieJar()))
        self.csrf=None
        self.records=[]

    def request(self,path,method='GET',data=None,key=None,csrf=True):
        headers={}
        if data is not None:
            headers['Content-Type']='application/json'
        if csrf and self.csrf:
            headers['X-CSRF-Token']=self.csrf
        if key:
            headers['Idempotency-Key']=key
        req=Request(self.base+path,data=None if data is None else json.dumps(data).encode(),
                    headers=headers,method=method)
        start=time.monotonic()
        try:
            response=self.opener.open(req,timeout=10)
        except HTTPError as exc:
            response=exc
        with response:
            body=response.read(65537)
            if len(body)>65536:
                raise ValueError('Response exceeded bounded probe body size')
            payload=json.loads(body)
            self.records.append({'method':method,'path':path,'status':response.code,
                'duration_ms':round((time.monotonic()-start)*1000,2),
                'request_id':response.headers.get('X-Request-ID',''),
                'version':payload.get('version')})
            return response.code,payload

    def login(self,user,password):
        status,data=self.request('/api/session')
        expect(status==200,'session')
        self.csrf=data['csrf']
        status,data=self.request('/api/login','POST',{'username':user,'password':password})
        expect(status==200,'login')
        self.csrf=data['csrf']

def expect(condition,check):
    if not condition:
        raise ValueError('Check failed: '+check)

def journey(base,logins,allow_loopback_http=False):
    clients={u:Client(base,allow_loopback_http) for u in ['alice','bob','operator']}
    a,b,operator=[clients[u] for u in ['alice','bob','operator']]
    expect(a.request('/api/bookings')[0]==401,'anonymous boundary')
    for user,client in clients.items():
        client.login(user,logins[user])
    expect(a.request('/api/bookings','POST',{'slot_id':1},csrf=False)[0]==403,'CSRF boundary')
    status,data=a.request('/api/slots')
    expect(status==200,'list slots')
    own=a.request('/api/bookings')[1]['bookings']
    active={row['slot_id'] for row in own if row['status']=='confirmed'}
    slot=next((s for s in data['slots'] if s['booked']<s['capacity'] and s['id'] not in active),None)
    expect(slot is not None,'available slot (cancel old demo reservations first)')
    key='probe-'+secrets.token_hex(12)
    booking_id=None
    try:
        status,data=a.request('/api/bookings','POST',{'slot_id':slot['id']},key)
        expect(status==201,'reserve')
        booking_id=data['booking']['id']
        status,data=a.request('/api/bookings','POST',{'slot_id':slot['id']},key)
        expect(status==200 and data['replayed'] and data['booking']['id']==booking_id,'idempotent replay')
        expect(b.request('/api/bookings/'+booking_id)[0]==404,'other user read denied')
        expect(b.request('/api/bookings/'+booking_id+'/cancel','POST',{})[0]==404,'other user cancellation denied')
        expect(a.request('/api/operator/bookings')[0]==403,'operator role boundary')
        expect(operator.request('/api/operator/bookings')[0]==200,'operator read')
        for replay in [False,True]:
            status,data=a.request('/api/bookings/'+booking_id+'/cancel','POST',{})
            expect(status==200 and data['replayed']==replay,'cancel exactly one business effect')
    finally:
        if booking_id:
            # Best-effort only for the booking made by this probe, never cancel unrelated rows.
            a.request('/api/bookings/'+booking_id+'/cancel','POST',{})
    return {'mode':'journey','checks':'completed','requests':[r for c in clients.values() for r in c.records]}

def capacity_race(base,logins,allow_loopback_http=False):
    clients={u:Client(base,allow_loopback_http) for u in ['alice','bob','operator']}
    for user,c in clients.items():
        c.login(user,logins[user])
    slot=next(s for s in clients['alice'].request('/api/slots')[1]['slots'] if s['id']==1)
    expect(slot['capacity']==2 and slot['booked']==0,'race requires empty seeded slot 1 with capacity 2')
    from threading import Barrier,Lock
    lock=Lock()
    barrier=Barrier(3,timeout=15)
    created=[]
    def reserve(item):
        user,c=item
        barrier.wait()
        status,data=c.request('/api/bookings','POST',{'slot_id':1},'race-'+secrets.token_hex(12))
        if status==201:
            with lock:
                created.append((c,data['booking']['id']))
        return user,status,data
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(reserve,clients.items()))
        expect(sorted(status for _,status,_ in results)==[201,201,409],'two seats, three distinct users')
        final=next(s for s in clients['alice'].request('/api/slots')[1]['slots'] if s['id']==1)
        expect(final['booked']==2,'booked count at capacity')
    finally:
        for c,bid in created:
            c.request('/api/bookings/'+bid+'/cancel','POST',{})
    restored=next(s for s in clients['alice'].request('/api/slots')[1]['slots'] if s['id']==1)
    expect(restored['booked']==0,'race reservations returned')
    return {'mode':'race','checks':'completed','requests':[r for c in clients.values() for r in c.records]}

def read_load(base,logins,requests,workers,allow_loopback_http=False):
    if not 1<=requests<=200 or not 1<=workers<=8:
        raise ValueError('Limit requests to 1..200 and workers to 1..8')
    # One independent cookie jar per worker: urllib opener is not shared across threads.
    def worker(count):
        c=Client(base,allow_loopback_http)
        c.login('alice',logins['alice'])
        start=len(c.records)
        for _ in range(count):
            c.request('/api/slots')
        return c.records[start:]
    counts=[requests//workers+(i<requests%workers) for i in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        records=[r for batch in pool.map(worker,[n for n in counts if n]) for r in batch]
    durations=sorted(r['duration_ms'] for r in records)
    status_counts={str(s):sum(r['status']==s for r in records) for s in sorted({r['status'] for r in records})}
    return {'mode':'read-load','requests':records,'status_counts':status_counts,
            'sample_count':len(records),'p50_ms':statistics.median(durations),
            'p95_ms':durations[max(0,(95*len(durations)+99)//100-1)],
            'note':'Bounded authenticated reads only; not a production capacity claim'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',required=True)
    p.add_argument('--logins',required=True,help='Private demo-logins.json file, never inline passwords')
    p.add_argument('--mode',choices=['journey','read-load','race'],default='journey')
    p.add_argument('--requests',type=int,default=40)
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--allow-loopback-http',action='store_true')
    args=p.parse_args()
    try:
        logins=json.loads(Path(args.logins).read_text())
        if args.mode=='journey':
            result=journey(args.url,logins,args.allow_loopback_http)
        elif args.mode=='race':
            result=capacity_race(args.url,logins,args.allow_loopback_http)
        else:
            result=read_load(args.url,logins,args.requests,args.workers,args.allow_loopback_http)
        print(json.dumps(result,sort_keys=True))
        if args.mode=='read-load' and set(result['status_counts'])!={'200'}:
            raise SystemExit(2)
    except (ValueError,KeyError,OSError) as exc:
        # Exceptions may contain response data or URLs. Do not dump their values.
        print(json.dumps({'error':'probe_failed','type':type(exc).__name__,
                          'next':'Inspect request IDs in service logs; verify URL, login bundle, capacity and limits'}))
        raise SystemExit(2)
if __name__=='__main__':
    main()
