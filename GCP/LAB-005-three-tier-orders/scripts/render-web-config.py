"""Render standalone Nginx configuration; never execute or change a running service."""
import argparse
import ipaddress
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def render(vip,web_root,web_port=80,api_port=8080,allow_loopback=False,pid_file='/run/nginx.pid',temp_root='/var/lib/nginx'):
    ip=ipaddress.ip_address(vip)
    expected=ipaddress.ip_network('10.55.20.0/24')
    if ip.version!=4 or not (ip in expected or (allow_loopback and ip.is_loopback)):
        raise ValueError('Use the dedicated API-subnet VIP; loopback is tests only')
    if type(web_port) is not int or not 1<=web_port<=65535 or type(api_port) is not int or not 1<=api_port<=65535:
        raise ValueError('Invalid listener port')
    if not allow_loopback and api_port!=8080:
        raise ValueError('Production API port is fixed to 8080')
    path=Path(web_root).resolve()
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',str(path)):
        raise ValueError('Use an absolute whitespace-free release path, without Nginx directives')
    pid_path=Path(pid_file).resolve()
    temp_path=Path(temp_root).resolve()
    for extra in [pid_path,temp_path]:
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+',str(extra)):
            raise ValueError('Invalid Nginx filesystem path')
    values={'API_VIP':str(ip),'WEB_ROOT':str(path),'WEB_PORT':str(web_port),'API_PORT':str(api_port),
            'PID_FILE':str(pid_path),'TEMP_ROOT':str(temp_path)}
    source=(ROOT/'web/nginx.conf.template').read_text()
    for key,value in values.items():
        source=source.replace('{{'+key+'}}',value)
    if '{{' in source:
        raise ValueError('Unresolved configuration placeholder')
    return source

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api-vip',required=True)
    p.add_argument('--web-root',default='/opt/lab005/web/current')
    p.add_argument('--web-port',type=int,default=80)
    p.add_argument('--api-port',type=int,default=8080)
    p.add_argument('--allow-loopback-test',action='store_true')
    p.add_argument('--pid-file',default='/run/nginx.pid')
    p.add_argument('--temp-root',default='/var/lib/nginx')
    p.add_argument('--out',required=True)
    args=p.parse_args()
    config=render(args.api_vip,args.web_root,args.web_port,args.api_port,args.allow_loopback_test,args.pid_file,args.temp_root)
    with Path(args.out).open('x') as handle:
        handle.write(config)
    print('Created new config. Validate it with nginx -t before activating a release.')
if __name__=='__main__':
    main()
