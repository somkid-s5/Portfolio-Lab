"""Inspect <=5 dead letters without ack, or ack ONE fresh receipt after terminal proof/audit."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from dead_letter import DeadLetters,Receipt,bindings
from google.pubsub_v1.services.subscriber import SubscriberClient
from order_domain import canonical

spec=importlib.util.spec_from_file_location("lab007_operator_client",Path(__file__).with_name("operator-replay.py"))
operator=importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator)


def write_receipts(destination,receipts):
    target=Path(destination)
    target.mkdir(mode=0o700)  # New directory only: never overwrite tokens from an earlier pull.
    os.chmod(target,0o700)
    summaries=[]
    for receipt in receipts:
        name=receipt.summary["source_digest"]+".json"
        fd=os.open(target/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"wb") as handle:
            handle.write(canonical(receipt.private_value()))
            handle.flush()
            os.fsync(handle.fileno())
        summaries.append({**receipt.summary,"receipt_file":name})
    fd=os.open(target,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try:os.fsync(fd)
    finally:os.close(fd)
    return summaries


def build(project,number):
    bindings(project,number)  # Validate before ADC/client construction.
    if any(os.environ.get(name) for name in ("GOOGLE_APPLICATION_CREDENTIALS","PUBSUB_EMULATOR_HOST")):
        raise ValueError("keyless_cloud_shell_identity_required")
    return SubscriberClient()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",required=True)
    parser.add_argument("--project-number",required=True)
    commands=parser.add_subparsers(dest="mode",required=True)
    inspect=commands.add_parser("inspect")
    inspect.add_argument("--out",required=True)
    ack=commands.add_parser("ack")
    for name in ("receipt","portal","demo-logins","reason","journal"):
        ack.add_argument("--"+name,required=True)
    args=parser.parse_args()
    client=None
    try:
        if args.mode=="inspect":
            # Refuse existing output before leasing messages.
            if Path(args.out).exists():
                raise ValueError("new_receipt_directory_required")
            client=build(args.project,args.project_number)
            inspector=DeadLetters(client,args.project,args.project_number)
            receipts,held=inspector.inspect()
            summaries=write_receipts(args.out,receipts)
            print(json.dumps({"inspected":len(summaries),"held_unrecognized":held,
                "acknowledged":0,"messages":summaries},sort_keys=True))
        else:
            receipt=Receipt.load(operator.private_read(args.receipt,16384),args.project,args.project_number)
            # An immutable action key must be on disk before any server-side audit mutation.
            body=operator.journal(args.journal,args.portal,receipt.summary["event_id"],
                                  receipt.summary["source_digest"],args.reason)
            client=build(args.project,args.project_number)
            inspector=DeadLetters(client,args.project,args.project_number)
            inspector._fresh(receipt)  # Refuse stale tokens before login or mutation.
            portal=operator.Portal(args.portal)
            portal.login(args.demo_logins)
            def approve(event_id,digest):
                if digest!=body["source_digest"]:
                    raise ValueError("source_digest_mismatch")
                return portal.prepare(event_id,body)
            result=inspector.acknowledge(receipt,portal.verify,approve)
            print(json.dumps(result,sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"event":"dead_letter_action_not_confirmed",
            "next":"hold_repull_and_reconcile_do_not_create_new_order"}))
        return 2
    finally:
        if client is not None:
            try:client.transport.close()
            except Exception:pass


if __name__=="__main__":
    raise SystemExit(main())
