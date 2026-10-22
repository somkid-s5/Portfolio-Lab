"""Build a deterministic static docs release; no network or cloud writes."""
import argparse
import hashlib
from html import escape
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML_CACHE='public,max-age=60'
ASSET_CACHE='public,max-age=31536000,immutable'

def build(release,out):
    catalog=json.loads((ROOT/'content/releases.json').read_text())
    if release not in catalog:
        raise ValueError('Unknown release')
    out=Path(out)
    out.mkdir(parents=False,exist_ok=False)
    data=catalog[release]
    css=('body{font:18px/1.65 system-ui;color:#193344;background:#f5f8fb;margin:0}'
         'main{max-width:920px;margin:auto;padding:40px 24px}header,article{background:white;'
         'border:1px solid #d7e1e8;padding:28px;margin:20px 0}h1,h2{color:'+data['accent']+'}'
         'small{letter-spacing:2px}code{background:#e8eef4;padding:3px 6px}'
         'a{color:'+data['accent']+'}footer{color:#526174}').encode()
    digest=hashlib.sha256(css).hexdigest()
    asset=f'releases/{release}/assets/docs.{digest[:16]}.css'
    path=out/asset
    path.parent.mkdir(parents=True)
    path.write_bytes(css)
    steps=''.join('<li>'+escape(step)+'</li>' for step in data['steps'])
    page=('''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>'''+escape(data['title'])+'</title><link rel="stylesheet" href="/'+asset+'">'
'<main><header><small>FIELD NOTES / PUBLIC DOCUMENTATION</small><h1>'+escape(data['title'])+
'</h1><p>Release <code id="release">'+release+'</code> / version '+escape(data['version'])+
'</p><nav><a href="#quickstart">Quick start</a> · <a href="#troubleshooting">Troubleshooting</a>'
'</nav></header><article><h2>'+escape(data['heading'])+'</h2><p>'+escape(data['intro'])+
'</p><h2 id="quickstart">Quick start</h2><ol>'+steps+
'</ol><h2 id="troubleshooting">Troubleshooting</h2><details><summary>The status is not ready</summary>'
'<p>Check the training connection and record the reference ID. Do not share passwords or customer data.</p>'
'</details></article><footer>Demo content only. This page contains no customer data or credentials.</footer></main></html>').encode()
    (out/'index.html').write_bytes(page)
    files=[]
    for name,mime,cache in [(asset,'text/css',ASSET_CACHE),('index.html','text/html; charset=utf-8',HTML_CACHE)]:
        payload=(out/name).read_bytes()
        files.append({'path':name,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),
                      'content_type':mime,'cache_control':cache})
    manifest={'schema':1,'release':release,'files':files}
    (out/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True,choices=['v1','v2','bad'])
    parser.add_argument('--out',required=True,help='New directory only')
    args=parser.parse_args()
    manifest=build(args.release,args.out)
    print(json.dumps({'release':manifest['release'],'out':args.out,'files':len(manifest['files'])}))

if __name__=='__main__':
    main()
