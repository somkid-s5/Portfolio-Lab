"""Render URL maps locally. Does not call Google Cloud or modify DNS."""
import argparse
import json
from pathlib import Path
import re

def render(project,host,out):
    if not re.fullmatch('[a-z][a-z0-9-]{4,28}[a-z0-9]',project):
        raise ValueError('Expected Google Cloud project ID')
    if (len(host)>253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',host)):
        raise ValueError('Expected a DNS hostname, not a URL')
    out=Path(out)
    out.mkdir(parents=False,exist_ok=False)
    backend=f'https://www.googleapis.com/compute/v1/projects/{project}/global/backendBuckets/lab003-docs-backend'
    maps={
      'content-map.json':{'name':'lab003-content-map','defaultService':backend,
        'hostRules':[{'hosts':[host],'pathMatcher':'docs-paths'}],
        'pathMatchers':[{'name':'docs-paths','defaultService':backend,
          'pathRules':[{'paths':['/'],'urlRedirect':{'pathRedirect':'/index.html',
                       'redirectResponseCode':'MOVED_PERMANENTLY_DEFAULT','stripQuery':False}}]}]},
      'http-redirect-map.json':{'name':'lab003-http-redirect','defaultUrlRedirect':{
         'httpsRedirect':True,'redirectResponseCode':'MOVED_PERMANENTLY_DEFAULT','stripQuery':False}}
    }
    for name,value in maps.items():
        (out/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
    return maps

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--host',required=True)
    parser.add_argument('--out',required=True,help='New directory only')
    args=parser.parse_args()
    render(args.project,args.host,args.out)
    print('Local URL maps rendered. Confirm ownership/DNS and inspect before importing.')

if __name__=='__main__':
    main()
