"""Verify runtime identity cannot access the bootstrap admin secret. Never output payload."""
import argparse
import re

def check(session,project,version):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]",project):
        raise ValueError('Expected project ID')
    if not re.fullmatch(r"[1-9][0-9]{0,8}",version):
        raise ValueError('Pin a numeric admin secret version')
    url=f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets/lab004-bootstrap-admin/versions/{version}:access"
    response=session.get(url,timeout=10,allow_redirects=False)
    try:
        status=response.status_code
        if status!=403:
            raise ValueError('Expected permission denied (403), received '+str(status))
        return {'check':'runtime_cannot_read_bootstrap_admin','status':status,'denied':True}
    finally:
        response.close()

def main():
    import json
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',required=True)
    p.add_argument('--version',required=True)
    args=p.parse_args()
    credentials,_=google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    with AuthorizedSession(credentials) as session:
        print(json.dumps(check(session,args.project,args.version)))
if __name__=='__main__':
    main()
