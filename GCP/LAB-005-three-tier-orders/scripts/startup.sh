#!/bin/bash
# Dedicated Debian 12 GCE VM only. Metadata is deployment-author controlled code.
set -eu
umask 077
export PYTHONDONTWRITEBYTECODE=1
/usr/bin/python3 - <<'LAB005_PY'
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import Request,build_opener,HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def decode_bundle(raw):
    if len(raw)>262144:
        raise ValueError('Bootstrap metadata too large')
    value=json.loads(base64.b64decode(raw.strip(),validate=True))
    if not isinstance(value,dict) or set(value)!={'release.py','vm-install.py'}:
        raise ValueError('Unexpected bootstrap files')
    result={}
    for name,source in value.items():
        if not isinstance(source,str) or not 1<=len(source.encode())<=100000:
            raise ValueError('Invalid bootstrap source')
        compile(source,name,'exec')
        result[name]=source.encode()
    return result

def launch(files,parent='/run',run=subprocess.run):
    # No deletion: private /run directory is ephemeral and useful for diagnosis.
    directory=Path(tempfile.mkdtemp(prefix='lab005-startup-',dir=parent))
    os.chmod(directory,0o700)
    for name,source in files.items():
        if name not in ('release.py','vm-install.py'):
            raise ValueError('Unexpected bootstrap filename')
        with (directory/name).open('xb') as handle:
            os.fchmod(handle.fileno(),0o600)
            handle.write(source)
    environment={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','HOME':'/nonexistent',
                 'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
    result=run(['/usr/bin/python3',str(directory/'vm-install.py')],
               env=environment,timeout=900,check=False)
    return result.returncode

def main():
    try:
        if os.geteuid()!=0:
            raise PermissionError('GCE root startup required')
        request=Request('http://metadata.google.internal/computeMetadata/v1/instance/attributes/lab005-bootstrap-code',
                        headers={'Metadata-Flavor':'Google'})
        with build_opener(NoRedirect()).open(request,timeout=15) as response:
            raw=response.read(262145)
        return launch(decode_bundle(raw))
    except Exception as exc:
        print(json.dumps({'event':'startup_failed','error_type':type(exc).__name__}),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
LAB005_PY
