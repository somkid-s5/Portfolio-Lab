"""Render a reproducible Cloud Run command; execute only with --execute."""
import argparse
import re
import shlex
import subprocess

def bounded_version(value):
    if not re.fullmatch(r"[1-9][0-9]{0,8}",value):
        raise argparse.ArgumentTypeError("Pin a numeric Secret Manager version, not latest")
    return value

def command(args):
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]",args.project):
        raise ValueError("Expected a project ID")
    if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]",args.region):
        raise ValueError("Expected a regional location")
    prefix=f"{args.region}-docker.pkg.dev/{args.project}/lab004-images/booking@sha256:"
    if not args.image.startswith(prefix) or not re.fullmatch(r"[a-f0-9]{64}",args.image[len(prefix):]):
        raise ValueError("Use a digest pinned to this project's lab004-images/booking repository")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}[a-z0-9]",args.suffix):
        raise ValueError("Use a unique 2-32 character revision suffix")
    env={"DB_MODE":"cloud","INSTANCE_CONNECTION_NAME":f"{args.project}:{args.region}:lab004-sql",
         "DB_CONFIG_FILE":"/secrets/db/config.json","AUTH_CONFIG_FILE":"/secrets/auth/config.json",
         "APP_VERSION":args.app_version}
    cmd=["gcloud","run","deploy","lab004-booking","--project",args.project,"--region",args.region,
         "--image",args.image,"--service-account",f"lab004-runtime@{args.project}.iam.gserviceaccount.com",
         "--execution-environment","gen2","--network","lab004-vpc","--subnet","lab004-run-subnet",
         "--vpc-egress","private-ranges-only","--allow-unauthenticated",
         "--cpu","1","--memory","512Mi","--min-instances","0","--max-instances","2",
         "--concurrency",str(args.concurrency),"--timeout","30","--port","8080",
         "--revision-suffix",args.suffix,
         "--set-env-vars",",".join(k+"="+v for k,v in env.items()),
         "--set-secrets",f"/secrets/db/config.json=lab004-db-{args.login}:{args.db_version},/secrets/auth/config.json=lab004-auth:{args.auth_version}",
         "--startup-probe","httpGet.path=/livez,httpGet.port=8080,periodSeconds=5,timeoutSeconds=2,failureThreshold=20",
         "--liveness-probe","httpGet.path=/livez,httpGet.port=8080,periodSeconds=30,timeoutSeconds=2,failureThreshold=3"]
    if args.candidate:
        cmd.extend(["--no-traffic","--tag","candidate"])
    return cmd

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project",required=True)
    p.add_argument("--region",default="asia-southeast1")
    p.add_argument("--image",required=True)
    p.add_argument("--auth-version",required=True,type=bounded_version)
    p.add_argument("--db-version",required=True,type=bounded_version)
    p.add_argument("--login",choices=["a","b"],default="a")
    p.add_argument("--app-version",choices=["v1","v2"],default="v1")
    p.add_argument("--concurrency",type=int,choices=[8,16],default=8)
    p.add_argument("--suffix",required=True)
    p.add_argument("--candidate",action="store_true",help="Existing service only: tagged revision with zero main traffic")
    p.add_argument("--execute",action="store_true")
    args=p.parse_args()
    cmd=command(args)
    print(shlex.join(cmd),flush=True)
    if args.execute:
        subprocess.run(cmd,check=True,timeout=600)
    else:
        print("DRY RUN: no cloud write. Review, then add --execute.")
if __name__=="__main__":
    main()
