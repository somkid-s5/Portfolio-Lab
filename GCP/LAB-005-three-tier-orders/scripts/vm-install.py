"""Debian GCE installer for dedicated Lab005 VMs. No provisioning; startup execution only."""
import base64
import fcntl
import hashlib
import runpy
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
from urllib.request import Request,build_opener,HTTPRedirectHandler
from release import inspect_archive,unpack,MAX_ARCHIVE

META='http://metadata.google.internal/computeMetadata/v1/'
MANAGED='# Managed by Portfolio-Lab LAB-005\n'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def crc32c(data):
    value=0xffffffff
    for byte in data:
        value^=byte
        for _ in range(8):
            value=(value>>1)^(0x82f63b78 if value&1 else 0)
    return value^0xffffffff

class Cloud:
    def __init__(self):
        self.opener=build_opener(NoRedirect())
        self._token=None

    def read(self,url,limit,metadata=False):
        headers={'Metadata-Flavor':'Google'} if metadata else {'Authorization':'Bearer '+self.token()}
        with self.opener.open(Request(url,headers=headers),timeout=30) as response:
            result=response.read(limit+1)
        if len(result)>limit:
            raise ValueError('Response exceeds bound')
        return result

    def metadata(self,path):
        return self.read(META+path,65536,True).decode().strip()

    def token(self):
        if self._token is None:
            value=json.loads(self.metadata('instance/service-accounts/default/token'))['access_token']
            if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9._~+/-]{10,4096}',value):
                raise ValueError('Invalid metadata token')
            self._token=value
        return self._token

    def artifact(self,bucket,checksum,tier):
        name='releases/'+checksum+'/'+tier+'.tar.gz'
        url='https://storage.googleapis.com/storage/v1/b/'+bucket+'/o/'+quote(name,safe='')+'?alt=media'
        return self.read(url,MAX_ARCHIVE)

    def secret(self,project,name,version):
        url=f'https://secretmanager.googleapis.com/v1/projects/{project}/secrets/{name}/versions/{version}:access'
        payload=json.loads(self.read(url,131072))['payload']
        data=base64.b64decode(payload['data'],validate=True)
        expected=payload.get('dataCrc32c')
        if len(data)>65536 or not isinstance(expected,str) or not expected.isdigit() or crc32c(data)!=int(expected):
            raise ValueError('Secret checksum or size invalid')
        return data

def settings(cloud):
    if cloud.metadata('instance/attributes/lab005-managed')!='true':
        raise ValueError('Requires dedicated managed Lab005 VM')
    role=cloud.metadata('instance/attributes/lab005-tier')
    if role not in ('web','api','init'):
        raise ValueError('Invalid VM tier')
    project=cloud.metadata('project/project-id')
    if not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]',project):
        raise ValueError('Invalid project ID')
    sa='bootstrap' if role=='init' else role
    if cloud.metadata('instance/service-accounts/default/email')!=f'lab005-{sa}@{project}.iam.gserviceaccount.com':
        raise ValueError('Unexpected VM service account')
    value={'role':role,'project':project,
           'bucket':cloud.metadata('instance/attributes/lab005-artifact-bucket'),
           'sha256':cloud.metadata('instance/attributes/lab005-artifact-sha256')}
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]',value['bucket']) or not re.fullmatch(r'[a-f0-9]{64}',value['sha256']):
        raise ValueError('Invalid artifact reference')
    if role=='web':
        vip=cloud.metadata('instance/attributes/lab005-api-vip')
        if ipaddress.ip_address(vip) not in ipaddress.ip_network('10.55.20.0/24'):
            raise ValueError('API VIP outside dedicated subnet')
        value['api_vip']=vip
    else:
        value['instance']=cloud.metadata('instance/attributes/lab005-sql-instance')
        if value['instance']!=project+':asia-southeast1:lab005-sql':
            raise ValueError('Unexpected SQL instance')
        for key in (['db','auth'] if role=='api' else ['db','admin']):
            version=cloud.metadata('instance/attributes/lab005-'+key+'-version')
            if not re.fullmatch('[1-9][0-9]{0,8}',version):
                raise ValueError('Pin numeric Secret versions')
            value[key+'_version']=version
    return value

def command(args,env=None,timeout=300):
    # Do not stream output: package/bootstrap errors can retain sensitive context.
    return subprocess.run(args,env=env,capture_output=True,check=True,timeout=timeout)

def atomic(path,data,mode=0o644,uid=0,gid=0):
    path=Path(path)
    if path.is_symlink():
        raise ValueError('Refusing symlink managed file')
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.lab005-',delete=False) as handle:
        temporary=Path(handle.name)
        try:
            os.fchmod(handle.fileno(),mode)
            os.fchown(handle.fileno(),uid,gid)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temporary,path)
        finally:
            temporary.unlink(missing_ok=True)

def verify_existing(target,files):
    if target.is_symlink() or not target.is_dir():
        raise ValueError('Invalid existing release directory')
    entries=list(target.rglob('*'))
    if any(path.is_symlink() for path in entries):
        raise ValueError('Linked existing release')
    actual={path.relative_to(target).as_posix() for path in entries if path.is_file()}
    if actual!=set(files):
        raise ValueError('Existing release layout differs')
    for name,data in files.items():
        path=target/name
        if path.stat().st_size!=len(data) or path.read_bytes()!=data:
            raise ValueError('Existing release modified; recreate VM instead of overwriting')

def api_unit(code,venv,envfile):
    return MANAGED+f'''[Unit]
Description=Lab005 Orders API
After=network-online.target
Wants=network-online.target
[Service]
User=lab005-api
Group=lab005-api
WorkingDirectory={code}/app
EnvironmentFile={envfile}
Environment=HOME=/nonexistent
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONUNBUFFERED=1
ExecStart={venv}/bin/gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 8 --timeout 30 main:create_app()
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
[Install]
WantedBy=multi-user.target
'''

def env_text(values):
    for key,value in values.items():
        if not re.fullmatch('[A-Z_]+',key) or not re.fullmatch(r'[A-Za-z0-9_./:-]+',str(value)):
            raise ValueError('Unsafe environment reference')
    return ''.join(key+'='+str(value)+'\n' for key,value in sorted(values.items()))

def runtime_user(run):
    try:
        return pwd.getpwnam('lab005-api')
    except KeyError:
        run(['useradd','--system','--user-group','--home-dir','/nonexistent',
             '--shell','/usr/sbin/nologin','lab005-api'])
        return pwd.getpwnam('lab005-api')

def wait_live(port):
    opener=build_opener(NoRedirect())
    for _ in range(20):
        try:
            with opener.open('http://127.0.0.1:'+str(port)+'/livez',timeout=2) as response:
                if response.status==200:
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError('Process liveness did not become ready')

def install(cloud,root=Path('/'),run=command,account=None,waiter=wait_live,owner_uid=0,owner_gid=0):
    cfg=settings(cloud)
    tier='api' if cfg['role']=='init' else cfg['role']
    archive=cloud.artifact(cfg['bucket'],cfg['sha256'],tier)
    metadata,files=inspect_archive(archive,cfg['sha256'],tier)
    print(json.dumps({'event':'install_stage','stage':'verified_bundle','tier':cfg['role']}),flush=True)
    root=Path(root).resolve()
    base=root/'opt/lab005'
    target=base/'releases'/cfg['sha256']
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() or target.is_symlink():
        verify_existing(target,files)
    else:
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.archive-',delete=False) as handle:
            temporary=Path(handle.name)
            handle.write(archive)
        try:
            unpack(temporary,cfg['sha256'],tier,target)
        finally:
            temporary.unlink(missing_ok=True)
    environment=dict(os.environ,DEBIAN_FRONTEND='noninteractive')
    run(['apt-get','update'],env=environment,timeout=180)
    run(['apt-get','install','-y','--no-install-recommends',
         'nginx' if tier=='web' else 'python3-venv'],env=environment,timeout=300)
    state=root/'var/lib/lab005'
    state.mkdir(parents=True,exist_ok=True)
    if tier=='web':
        renderer=runpy.run_path(str(target/'scripts/render-web-config.py'))
        config=(MANAGED+renderer['render'](cfg['api_vip'],str(target/'web'))).encode()
        candidate=root/'etc/lab005/nginx.candidate.conf'
        atomic(candidate,config,uid=owner_uid,gid=owner_gid)
        run(['nginx','-t','-c',str(candidate)])
        active=root/'etc/nginx/nginx.conf'
        if active.exists() and not active.read_bytes().startswith(MANAGED.encode()):
            backup=root/'etc/nginx/nginx.conf.lab005-before'
            if backup.exists():
                raise ValueError('Unmanaged Nginx config and previous backup exist; inspect before replacing')
            atomic(backup,active.read_bytes(),uid=owner_uid,gid=owner_gid)
        atomic(active,config,uid=owner_uid,gid=owner_gid)
        run(['systemctl','enable','nginx'])
        run(['systemctl','restart','nginx'])
        waiter(80)
    else:
        venv=base/'venvs'/cfg['sha256']
        venv.parent.mkdir(parents=True,exist_ok=True)
        requirement_hash=hashlib.sha256(files['requirements.txt']).hexdigest().encode()
        complete=venv/'.requirements-sha256'
        if venv.exists():
            if not complete.is_file() or complete.read_bytes()!=requirement_hash:
                raise ValueError('Incomplete venv; inspect/recreate VM instead of overwriting')
        else:
            run(['python3','-m','venv',str(venv)],timeout=120)
            run([str(venv/'bin/pip'),'install','--disable-pip-version-check','-r',str(target/'requirements.txt')],timeout=300)
            atomic(complete,requirement_hash,uid=owner_uid,gid=owner_gid)
        credentials=state/(cfg['role']+'-'+cfg['sha256'])
        if credentials.is_symlink():
            raise ValueError('Refusing linked credentials directory')
        credentials.mkdir(mode=0o750,exist_ok=True)
        user=(account or runtime_user(run)) if cfg['role']=='api' else None
        group=user.pw_gid if user else owner_gid
        os.chown(credentials,owner_uid,group)
        os.chmod(credentials,0o750 if user else 0o700)
        runtime=cloud.secret(cfg['project'],'lab005-db',cfg['db_version'])
        parsed=json.loads(runtime)
        if parsed.get('user')!='orders_app' or parsed.get('database')!='orders' or not re.fullmatch(r'[A-Za-z0-9_-]{32,100}',parsed.get('password','')):
            raise ValueError('Unexpected runtime DB configuration')
        runtime_file=credentials/'db.json'
        atomic(runtime_file,runtime,0o640 if user else 0o600,owner_uid,group)
        values={'DB_MODE':'cloud','DEPLOYMENT_TARGET':'gce','INSTANCE_CONNECTION_NAME':cfg['instance'],
                'APP_VERSION':metadata['app_version'],'DB_CONFIG_FILE':str(runtime_file)}
        if cfg['role']=='init':
            admin=cloud.secret(cfg['project'],'lab005-bootstrap-admin',cfg['admin_version'])
            parsed=json.loads(admin)
            if parsed.get('user')!='postgres' or parsed.get('database')!='orders':
                raise ValueError('Unexpected bootstrap DB configuration')
            admin_file=credentials/'admin.json'
            atomic(admin_file,admin,0o600,owner_uid,owner_gid)
            values['DB_CONFIG_FILE']=str(admin_file)
            child={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':'/nonexistent',
                   'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1',**values}
            run([str(venv/'bin/python'),str(target/'scripts/init-db.py'),'--runtime-file',str(runtime_file)],
                env=child,timeout=60)
        else:
            auth=cloud.secret(cfg['project'],'lab005-auth',cfg['auth_version'])
            parsed=json.loads(auth)
            if not isinstance(parsed.get('session_key'),str) or len(parsed['session_key'])<64 or not parsed.get('users'):
                raise ValueError('Unexpected auth configuration')
            auth_file=credentials/'auth.json'
            atomic(auth_file,auth,0o640,owner_uid,group)
            values['AUTH_CONFIG_FILE']=str(auth_file)
            envfile=root/'etc/lab005/api.env'
            atomic(envfile,env_text(values).encode(),0o600,owner_uid,owner_gid)
            unit=root/'etc/systemd/system/lab005-api.service'
            if unit.exists() and not unit.read_bytes().startswith(MANAGED.encode()):
                raise ValueError('Refusing unmanaged API service unit')
            atomic(unit,api_unit(target,venv,envfile).encode(),uid=owner_uid,gid=owner_gid)
            run(['systemctl','daemon-reload'])
            run(['systemctl','enable','lab005-api'])
            run(['systemctl','restart','lab005-api'])
            waiter(8080)
    print(json.dumps({'event':'install_complete','tier':cfg['role'],'source_commit':metadata['source_commit'],
                      'sha256':cfg['sha256'],'cloud_verification':'not-asserted'}),flush=True)
    return cfg

def main():
    try:
        if os.geteuid()!=0:
            raise PermissionError('Dedicated GCE root startup required')
        Path('/run/lab005').mkdir(mode=0o700,exist_ok=True)
        with Path('/run/lab005/install.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            install(Cloud())
        return 0
    except Exception as exc:
        print(json.dumps({'event':'install_failed','error_type':type(exc).__name__,
                          'next':'Inspect startup stage, IAM, artifact hash, package/NAT and service logs; do not print secrets'}),file=sys.stderr)
        return 2
if __name__=='__main__':
    raise SystemExit(main())
