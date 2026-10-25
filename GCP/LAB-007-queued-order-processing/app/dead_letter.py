"""Bounded pull/inspect and terminal+audit-gated ack. No automatic replay or ack."""
from dataclasses import dataclass
import hashlib
import re
import time

from google.pubsub_v1.types import PullRequest,AcknowledgeRequest
from order_domain import canonical,identifier,parse_event,read_json

MAX_MESSAGES=5
MAX_RECEIPT_AGE=90
FIELDS={"project","project_number","source_subscription","message_id","event_id","order_id",
        "order_fingerprint","data_sha256","canonical_sha256","schema_version","source_digest","source_delivery_count"}


def bindings(project,number):
    if (not isinstance(project,str) or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]",project)
            or not isinstance(number,str) or not re.fullmatch(r"[1-9][0-9]{5,19}",number)):
        raise ValueError("invalid_project_binding")
    return (f"projects/{project}/subscriptions/lab007-orders-worker",
            f"projects/{project}/subscriptions/lab007-orders-dead-inspect")


def digest_for(summary):
    return hashlib.sha256(canonical({key:summary[key] for key in FIELDS-{"source_digest"}})).hexdigest()


def checked_summary(value,project,number):
    source,_=bindings(project,number)
    if not isinstance(value,dict) or set(value)!=FIELDS:
        raise ValueError("invalid_receipt")
    if (value["project"]!=project or value["project_number"]!=number or
            value["source_subscription"]!=source or not isinstance(value["message_id"],str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",value["message_id"])
            or type(value["schema_version"]) is not int or value["schema_version"] not in (1,99)):
        raise ValueError("invalid_receipt_binding")
    count=value["source_delivery_count"]
    if count is not None and (type(count) is not int or not 1<=count<=100000000):
        raise ValueError("invalid_delivery_observation")
    identifier(value["event_id"])
    identifier(value["order_id"])
    for key in ("order_fingerprint","data_sha256","canonical_sha256","source_digest"):
        if not isinstance(value[key],str) or not re.fullmatch(r"[a-f0-9]{64}",value[key]):
            raise ValueError("invalid_receipt_hash")
    if value["source_digest"]!=digest_for(value):
        raise ValueError("receipt_digest_mismatch")
    return dict(value)


def inspect_message(message,project,number):
    source,_=bindings(project,number)
    data=bytes(message.data)
    if not 1<=len(data)<=4096:
        raise ValueError("invalid_source_data_size")
    attributes=dict(message.attributes)
    if len(attributes)>100 or any(not isinstance(k,str) or not isinstance(v,str) or
            len(k.encode("utf-8"))>256 or len(v.encode("utf-8"))>1024 for k,v in attributes.items()):
        raise ValueError("invalid_source_attributes")
    if (attributes.get("CloudPubSubDeadLetterSourceSubscription") not in (source,"lab007-orders-worker") or
            attributes.get("CloudPubSubDeadLetterSourceSubscriptionProject") not in (project,number)):
        raise ValueError("unexpected_forward_source")
    count=attributes.get("CloudPubSubDeadLetterSourceDeliveryCount")
    if count is not None:
        if not isinstance(count,str) or not re.fullmatch(r"[0-9]{1,9}",count):
            raise ValueError("invalid_delivery_observation")
        count=int(count)
        if not 1<=count<=100000000:
            raise ValueError("invalid_delivery_observation")
    value=read_json(data)
    version=value.get("schema_version")
    if type(version) is not int or version not in (1,99) or data!=canonical(value):
        raise ValueError("unsupported_forward_data")
    # 99 is this Lab's explicit schema-only poison fixture, not a generic repair.
    original=canonical({**value,"schema_version":1})
    event=parse_event(original)
    summary={"project":project,"project_number":number,"source_subscription":source,
             "message_id":message.message_id,"event_id":event.event_id,"order_id":event.order_id,
             "order_fingerprint":event.order_fingerprint,"data_sha256":hashlib.sha256(data).hexdigest(),
             "canonical_sha256":hashlib.sha256(original).hexdigest(),"schema_version":version,
             "source_delivery_count":count}
    summary["source_digest"]=digest_for(summary)
    return checked_summary(summary,project,number)


@dataclass(frozen=True,repr=False)
class Receipt:
    summary:dict
    ack_id:str
    pulled_at:float

    def private_value(self):
        return {"summary":dict(self.summary),"ack_id":self.ack_id,"pulled_at":self.pulled_at}

    @classmethod
    def load(cls,value,project,number):
        if not isinstance(value,dict) or set(value)!={"summary","ack_id","pulled_at"}:
            raise ValueError("invalid_receipt")
        if (not isinstance(value["ack_id"],str) or not 1<=len(value["ack_id"])<=4096 or
                any(ord(c)<33 or ord(c)>126 for c in value["ack_id"]) or
                type(value["pulled_at"]) not in (int,float) or
                not 0<=value["pulled_at"]<=32503680000):
            raise ValueError("invalid_receipt")
        return cls(checked_summary(value["summary"],project,number),value["ack_id"],value["pulled_at"])


class DeadLetters:
    def __init__(self,client,project,project_number,*,clock=time.time):
        _,self.subscription=bindings(project,project_number)
        self.client,self.project,self.number,self.clock=client,project,project_number,clock

    def inspect(self):
        try:
            response=self.client.pull(request=PullRequest(subscription=self.subscription,
                max_messages=MAX_MESSAGES),retry=None,timeout=10)
        except Exception:
            raise ValueError("inspect_unconfirmed_no_ack") from None
        messages=list(response.received_messages)
        if len(messages)>MAX_MESSAGES:
            raise ValueError("too_many_messages_no_ack")
        receipts=[]
        held=0
        for received in messages:
            try:
                summary=inspect_message(received.message,self.project,self.number)
                receipt=Receipt.load({"summary":summary,"ack_id":received.ack_id,
                    "pulled_at":self.clock()},self.project,self.number)
            except (ValueError,TypeError,UnicodeError):
                held+=1
                continue
            receipts.append(receipt)
        return receipts,held

    def _fresh(self,receipt):
        receipt=Receipt.load(receipt.private_value(),self.project,self.number)
        age=self.clock()-receipt.pulled_at
        if not 0<=age<=MAX_RECEIPT_AGE:
            raise ValueError("receipt_expired_repull_no_ack")
        return receipt

    def acknowledge(self,receipt,verify,approve):
        receipt=self._fresh(receipt)
        expected=receipt.summary
        proof=verify(expected["event_id"])
        if (not isinstance(proof,dict) or proof.get("terminal_verified") is not True or
                proof.get("order_state") not in ("confirmed","rejected") or
                proof.get("event_id")!=expected["event_id"] or
                proof.get("order_id")!=expected["order_id"] or
                proof.get("order_fingerprint")!=expected["order_fingerprint"] or
                proof.get("payload_sha256")!=expected["canonical_sha256"]):
            raise ValueError("terminal_binding_not_verified_no_ack")
        self._fresh(receipt)
        approval=approve(expected["event_id"],expected["source_digest"])
        if (not isinstance(approval,dict) or approval.get("outcome")!="already_resolved" or
                approval.get("event_id")!=expected["event_id"] or
                approval.get("source_digest")!=expected["source_digest"] or
                type(approval.get("replayed")) is not bool or
                type(approval.get("epoch")) is not int or not 0<=approval["epoch"]<=2):
            raise ValueError("terminal_audit_not_confirmed_no_ack")
        self._fresh(receipt)  # Verification/login may have consumed the receipt's lease window.
        try:
            self.client.acknowledge(request=AcknowledgeRequest(subscription=self.subscription,
                ack_ids=[receipt.ack_id]),retry=None,timeout=5)
        except Exception:
            raise ValueError("ack_unconfirmed_repull_and_reconcile") from None
        # Standard Pub/Sub ack response does not prove an expired token removed a message.
        return {"event_id":expected["event_id"],"source_digest":expected["source_digest"],
                "ack_request":"accepted","absence_verified":False}
