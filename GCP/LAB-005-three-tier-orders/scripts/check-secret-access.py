"""Prove attached VM identity cannot access a pinned Secret; never print token/payload."""
import argparse
import json
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPRedirectHandler,ProxyHandler

META='http://metadata.google.internal/computeMetadata/v1/'
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def check(secret,version,expected_sa,opener=None):
    if secret not in ('lab005-db','lab005-auth','lab005-bootstrap-admin') or not re.fullmatch('[1-9][0-9]{0,8}',version):
        raise ValueError('Expected allowed Secret and numeric version')
    opener=opener or build_opener(ProxyHandler({}),NoRedirect())
    def metadata(path):
        with opener.open(Request(META+path,headers={'Metadata-Flavor':'Google'}),timeout=5) as response:
            data=response.read(65537)
        if len(data)>65536: raise ValueError('Metadata exceeds bound')
        return data.decode().strip()
    project=metadata('project/project-id')
    if not re.fullmatch('[a-z][a-z0-9-]{4,28}[a-z0-9]',project):
        raise ValueError('Invalid project')
    allowed={f'lab005-{role}@{project}.iam.gserviceaccount.com' for role in ('web','api','diagnostic')}
    actual=metadata('instance/service-accounts/default/email')
    if actual!=expected_sa or actual not in allowed:
        raise ValueError('Unexpected attached VM identity')
    scopes=metadata('instance/service-accounts/default/scopes').splitlines()
    if 'https://www.googleapis.com/auth/cloud-platform' not in scopes:
        raise ValueError('Scope missing; cannot isolate IAM denial')
    token=json.loads(metadata('instance/service-accounts/default/token'))['access_token']
    if not isinstance(token,str) or not 10<=len(token)<=4096:
        raise ValueError('Invalid token')
    url=f'https://secretmanager.googleapis.com/v1/projects/{project}/secrets/{secret}/versions/{version}:access'
    try:
        with opener.open(Request(url,headers={'Authorization':'Bearer '+token}),timeout=5) as response:
            status=response.code
            # Do not read successful Secret data even when this negative test unexpectedly succeeds.
        return {'event':'secret_boundary','service_account':actual,'secret':secret,'version':version,
                'denied':False,'http_status':status}
    except HTTPError as exc:
        with exc:
            raw=exc.read(65537)
        if exc.code!=403 or len(raw)>65536:
            raise ValueError('Not a verified permission denial')
        error=json.loads(raw).get('error',{})
        reasons=[item.get('reason') for item in error.get('details',[]) if isinstance(item,dict)]
        if error.get('status')!='PERMISSION_DENIED' or 'ACCESS_TOKEN_SCOPE_INSUFFICIENT' in reasons:
            raise ValueError('Not a verified IAM boundary result')
        return {'event':'secret_boundary','service_account':actual,'secret':secret,'version':version,
                'denied':True,'http_status':403}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secret',required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--expected-sa',required=True)
    args=parser.parse_args()
    try:
        result=check(args.secret,args.version,args.expected_sa)
        print(json.dumps(result,sort_keys=True))
        return 0 if result['denied'] else 3
    except Exception as exc:
        print(json.dumps({'event':'boundary_check_failed','error_type':type(exc).__name__}),file=sys.stderr)
        return 2
if __name__=='__main__':
    raise SystemExit(main())
