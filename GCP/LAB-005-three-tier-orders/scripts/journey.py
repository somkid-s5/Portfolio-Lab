"""Bounded Orders journey with durable idempotency key; credentials never printed."""
import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import sys
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPCookieProcessor,HTTPRedirectHandler,ProxyHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def origin(value,local=False):
    url=urlsplit(value)
    if (not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/')):
        raise ValueError('Origin only')
    if local:
        if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost'):
            raise ValueError('Loopback HTTP test only')
    elif url.scheme!='https' or url.port not in (None,443):
        raise ValueError('Verified HTTPS required')
    return value.rstrip('/')

def private_json(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:
        raise ValueError('Expected bounded private file')
    if os.name=='posix' and path.stat().st_mode&0o077:
        raise ValueError('Private input must not be group/world readable')
    return json.loads(path.read_bytes())

def journal(path):
    path=Path(path)
    if path.exists() or path.is_symlink():
        value=private_json(path)
    else:
        value={'schema':1,'key':'journey-'+uuid.uuid4().hex,
               'items':[{'sku':'BOOK-01','quantity':1}]}
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as handle:
            json.dump(value,handle)
            handle.flush()
            os.fsync(handle.fileno())
    if (not isinstance(value,dict) or set(value)!={'schema','key','items'} or value['schema']!=1 or
        not isinstance(value['key'],str) or not re.fullmatch('journey-[a-f0-9]{32}',value['key']) or
        value['items']!=[{'sku':'BOOK-01','quantity':1}]):
        raise ValueError('Journal differs from fixed logical order')
    return value

class Client:
    def __init__(self,base):
        self.base=base
        self.csrf=None
        self.calls=0
        self.opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPCookieProcessor(CookieJar()))

    def request(self,method,path,payload=None,key=None,csrf=True):
        self.calls+=1
        if self.calls>20:
            raise ValueError('Request bound exceeded')
        headers={'Accept':'application/json'}
        if method=='POST' and csrf and self.csrf:
            headers['X-CSRF-Token']=self.csrf
        if key:
            headers['Idempotency-Key']=key
        data=None
        if payload is not None:
            data=json.dumps(payload).encode()
            headers['Content-Type']='application/json'
        request=Request(self.base+path,data=data,headers=headers,method=method)
        try:
            response=self.opener.open(request,timeout=5)
        except HTTPError as exc:
            response=exc
        with response:
            status=response.code
            raw=response.read(65537)
        if len(raw)>65536:
            raise ValueError('Response bound exceeded')
        result=json.loads(raw)
        if not isinstance(result,dict):
            raise ValueError('Unexpected JSON response')
        return status,result

    def login(self,user,password):
        status,data=self.request('GET','/api/session')
        if status!=200 or not isinstance(data.get('csrf'),str):
            raise ValueError('Session unavailable')
        self.csrf=data['csrf']
        status,data=self.request('POST','/api/login',{'username':user,'password':password})
        if status!=200 or not isinstance(data.get('csrf'),str):
            raise ValueError('Authentication failed')
        self.csrf=data['csrf']

def journey(base,logins,state):
    alice,bob=Client(base),Client(base)
    checks=[]
    def require(label,condition):
        if not condition:
            raise ValueError('Journey check failed: '+label)
        checks.append(label)
    require('anonymous-denied',alice.request('GET','/api/orders')[0]==401)
    alice.login('alice',logins['alice'])
    status,first=alice.request('POST','/api/orders',{'items':state['items']},state['key'])
    require('create-or-resume',status in (200,201) and isinstance(first.get('order'),dict))
    order=first['order']
    reference=str(uuid.UUID(order['id']))
    status,replay=alice.request('POST','/api/orders',{'items':state['items']},state['key'])
    require('same-key-same-order',status==200 and replay.get('replayed') is True and replay['order']['id']==reference)
    status,_=alice.request('POST','/api/orders',{'items':[{'sku':'BOOK-01','quantity':2}]},state['key'])
    require('changed-payload-conflict',status==409)
    status,_=alice.request('POST','/api/orders',{'items':state['items']},state['key'],csrf=False)
    require('csrf-denied',status==403)
    bob.login('bob',logins['bob'])
    require('other-owner-denied',bob.request('GET','/api/orders/'+reference)[0]==404)
    require('operator-role-denied',bob.request('GET','/api/operator/orders')[0]==403)
    for index in range(2):
        status,cancelled=alice.request('POST','/api/orders/'+reference+'/cancel',{})
        require('cancel-'+str(index+1),status==200 and cancelled['order']['status']=='cancelled')
        if index:
            require('cancel-replayed',cancelled.get('replayed') is True)
    return {'event':'journey_result','checks':checks,'order_id':reference,
            'requests':alice.calls+bob.calls,'status':'checks-completed',
            'next':'Run DB reconciliation; this result alone does not prove stock balance or failover.'}

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
        state=journal(args.journal)  # Persist BEFORE any order request.
        print(json.dumps(journey(base,logins,state),sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({'event':'journey_failed','error_type':type(exc).__name__,
                          'next':'Keep the same journal. Inspect the system and retry it; do not generate a new key after an ambiguous response.'}),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
