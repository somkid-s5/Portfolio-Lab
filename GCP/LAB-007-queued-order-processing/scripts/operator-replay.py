"""Prepare or resolve ONE canonical replay. No Pub/Sub pull/ack and no password arguments."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from order_domain import canonical,identifier,read_json
from replay import replay_request


def origin_url(value):
    if not isinstance(value,str) or len(value)>253:
        raise ValueError("invalid_portal_origin")
    parsed=urllib.parse.urlsplit(value)
    if (parsed.scheme!="https" or parsed.username is not None or parsed.password is not None
            or parsed.port is not None or parsed.path not in ("","/") or parsed.query or parsed.fragment
            or not re.fullmatch(r"lab007-portal-[a-z0-9]+(?:[.-][a-z0-9]+)*\.run\.app",parsed.hostname or "")):
        raise ValueError("invalid_portal_origin")
    return "https://"+parsed.hostname


def private_read(path,limit=4096):
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)
    descriptor=os.open(path,flags)
    with os.fdopen(descriptor,"rb") as handle:
        info=os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or (os.name=="posix" and stat.S_IMODE(info.st_mode)&0o077):
            raise ValueError("private_regular_file_required")
        return read_json(handle.read(limit+1),limit=limit)


def journal(path,origin,event_id,digest,reason):
    origin=origin_url(origin)
    identifier(event_id)
    target=Path(path)
    desired={"origin":origin,"event_id":event_id,"source_digest":digest,"reason":reason}
    parent=target.parent
    parent.mkdir(mode=0o700,exist_ok=True)
    if os.name=="posix" and stat.S_IMODE(parent.stat().st_mode)&0o077:
        raise ValueError("private_directory_required")
    # A partial file from a crash is intentionally NOT regenerated: operator must reconcile it.
    if not target.exists():
        value={**desired,"idempotency_key":uuid.uuid4().hex}
        replay_request(canonical({k:value[k] for k in ("idempotency_key","source_digest","reason")}))
        descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,"wb") as handle:
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        directory=os.open(parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try:os.fsync(directory)
        finally:os.close(directory)
    value=private_read(target)
    if set(value)!={*desired,"idempotency_key"} or any(value[k]!=v for k,v in desired.items()):
        raise ValueError("journal_mismatch_do_not_replace")
    body={k:value[k] for k in ("idempotency_key","source_digest","reason")}
    replay_request(canonical(body))
    return body


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("redirect_refused")


class Portal:
    def __init__(self,origin,*,opener=None):
        self.origin=origin_url(origin)
        self.opener=opener or urllib.request.build_opener(
            NoRedirect(),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf=None

    def request(self,path,body=None):
        if not re.fullmatch(r"/api/(?:session|login|operator/outbox/[a-f0-9]{32}/replay)",path):
            raise ValueError("invalid_api_route")
        headers={"Accept":"application/json"}
        if body is not None:
            headers.update({"Content-Type":"application/json","X-CSRF-Token":self.csrf or ""})
        request=urllib.request.Request(self.origin+path,
            data=canonical(body) if body is not None else None,headers=headers,
            method="POST" if body is not None else "GET")
        try:
            with self.opener.open(request,timeout=10) as response:
                if response.status!=200:
                    raise ValueError("unexpected_http_status")
                return read_json(response.read(65537),limit=65536)
        except urllib.error.HTTPError as error:
            status=error.code
            error.close()
            raise ValueError("portal_http_"+str(status)) from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise ValueError("outcome_unconfirmed_reuse_journal") from None

    def login(self,bundle):
        auth=private_read(bundle)
        operator=auth.get("operator")
        if (not isinstance(operator,dict) or set(operator)!={"password","role"}
                or operator["role"]!="operator" or not isinstance(operator["password"],str)
                or not 24<=len(operator["password"])<=128):
            raise ValueError("invalid_operator_bundle")
        first=self.request("/api/session")
        token=first.get("csrf")
        if not isinstance(token,str) or not re.fullmatch(r"[a-f0-9]{64}",token):
            raise ValueError("invalid_session_response")
        self.csrf=token
        logged=self.request("/api/login",{"username":"operator","password":operator["password"]})
        if logged.get("user")!="operator" or logged.get("role")!="operator":
            raise ValueError("operator_login_required")
        token=logged.get("csrf")
        if not isinstance(token,str) or not re.fullmatch(r"[a-f0-9]{64}",token):
            raise ValueError("invalid_session_response")
        self.csrf=token

    def prepare(self,event_id,body):
        identifier(event_id)
        replay_request(canonical(body))
        result=self.request("/api/operator/outbox/"+event_id+"/replay",body)
        if (result.get("event_id")!=event_id or result.get("source_digest")!=body["source_digest"]
                or result.get("reason")!=body["reason"] or result.get("outcome") not in ("prepared","already_resolved")
                or type(result.get("epoch")) is not int or not 0<=result["epoch"]<=2
                or type(result.get("replayed")) is not bool):
            raise ValueError("outcome_unconfirmed_reuse_journal")
        return {k:result[k] for k in ("event_id","source_digest","reason","outcome","epoch","replayed")}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("portal","demo-logins","event-id","source-digest","reason","journal"):
        parser.add_argument("--"+name,required=True)
    args=parser.parse_args()
    try:
        # Durable key must exist before any network mutation; never regenerate on unknown outcome.
        body=journal(args.journal,args.portal,args.event_id,args.source_digest,args.reason)
        client=Portal(args.portal)
        client.login(args.demo_logins)
        result=client.prepare(args.event_id,body)
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"event":"replay_not_confirmed",
                          "next":"inspect_or_retry_same_journal_do_not_ack_dead_letter"}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
