"""Fixed role-to-factory entrypoint; never evaluates a caller-supplied target or shell."""
import os


def command(environment):
    target={
        "portal":"portal_runtime:build_portal()",
        "worker":"queue_runtime:build_worker()",
        "dispatcher":"queue_runtime:build_dispatcher()",
    }.get(environment.get("SERVICE_ROLE"))
    port=environment.get("PORT","8080")
    if target is None or not isinstance(port,str) or not port.isascii() or not port.isdigit() or len(port)>5:
        raise ValueError("invalid_container_configuration")
    if not 1<=int(port)<=65535:
        raise ValueError("invalid_container_port")
    threads="4" if environment["SERVICE_ROLE"]=="portal" else "1"
    return ["/usr/local/bin/gunicorn","--bind","0.0.0.0:"+str(int(port)),
        "--workers","1","--threads",threads,"--timeout","65","--graceful-timeout","15",
        "--worker-tmp-dir","/tmp","--error-logfile","-",target]


if __name__=="__main__":
    try:
        arguments=command(os.environ)
    except ValueError:
        raise SystemExit("Invalid container configuration")
    os.execv(arguments[0],arguments)
