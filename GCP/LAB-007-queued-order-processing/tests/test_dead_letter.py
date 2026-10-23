"""Real protobuf/GAPIC contracts with mocked RPC. Never contacts Pub/Sub."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

from google.auth.credentials import AnonymousCredentials
from google.pubsub_v1.services.subscriber import SubscriberClient
from google.pubsub_v1.types import AcknowledgeRequest,PullRequest,PullResponse,PubsubMessage,ReceivedMessage
from google.protobuf.empty_pb2 import Empty

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
from dead_letter import DeadLetters,Receipt,bindings,checked_summary,inspect_message
from order_domain import canonical,event_bytes

spec=importlib.util.spec_from_file_location("dlq_cli",LAB/"scripts/dead-letter.py")
cli=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
PROJECT="demo-lab007"
NUMBER="123456789012"
SOURCE,SUB=bindings(PROJECT,NUMBER)
EVENT,ORDER,FP="a"*32,"b"*32,"c"*64
NOW=1792780000.0
ORIGIN="https://lab007-portal-123456789012.asia-southeast1.run.app"


def message(version=1,**changes):
    value={"schema_version":version,"event_id":EVENT,"order_id":ORDER,"order_fingerprint":FP}
    value.update(changes)
    return PubsubMessage(data=canonical(value),message_id="12345",attributes={
        "CloudPubSubDeadLetterSourceSubscription":SOURCE,
        "CloudPubSubDeadLetterSourceSubscriptionProject":PROJECT,
        "CloudPubSubDeadLetterSourceDeliveryCount":"11"})


def receipt():
    return Receipt(inspect_message(message(),PROJECT,NUMBER),"private-ack-token",NOW)


def proof():
    return {"event_id":EVENT,"order_id":ORDER,"order_fingerprint":FP,
            "payload_sha256":hashlib.sha256(event_bytes(EVENT,ORDER,FP)).hexdigest(),
            "order_state":"confirmed","terminal_verified":True}


def approval():
    return {"event_id":EVENT,"source_digest":receipt().summary["source_digest"],
            "outcome":"already_resolved","epoch":1,"replayed":False}


class DeadLetterTests(unittest.TestCase):
    def setUp(self):
        self.client=Mock()
        self.dead=DeadLetters(self.client,PROJECT,NUMBER,clock=lambda:NOW)
        self.verify=Mock(return_value=proof())
        self.approve=Mock(return_value=approval())

    def test_sdk_pull_is_single_bounded_rpc_and_never_acknowledges(self):
        self.client.pull.return_value=PullResponse(received_messages=[
            ReceivedMessage(message=message(),ack_id="private-ack-token")])
        receipts,held=self.dead.inspect()
        self.assertEqual((len(receipts),held),(1,0))
        call=self.client.pull.call_args
        self.assertIsInstance(call.kwargs["request"],PullRequest)
        self.assertEqual((call.kwargs["request"].subscription,call.kwargs["request"].max_messages),(SUB,5))
        self.assertEqual((call.kwargs["retry"],call.kwargs["timeout"]),(None,10))
        self.client.acknowledge.assert_not_called()
        self.assertNotIn("private-ack-token",repr(receipts[0]))
        self.assertEqual(receipts[0].summary["source_delivery_count"],11)  # Observation, not a hard counter.

    def test_broker_metadata_short_or_full_source_is_bound_to_configured_project(self):
        for subscription in (SOURCE,"lab007-orders-worker"):
            for project in (PROJECT,NUMBER):
                msg=message()
                msg.attributes["CloudPubSubDeadLetterSourceSubscription"]=subscription
                msg.attributes["CloudPubSubDeadLetterSourceSubscriptionProject"]=project
                self.assertEqual(inspect_message(msg,PROJECT,NUMBER)["event_id"],EVENT)
        for field,value in (("CloudPubSubDeadLetterSourceSubscription","projects/other/subscriptions/lab007-orders-worker"),
            ("CloudPubSubDeadLetterSourceSubscriptionProject","other-project"),
            ("CloudPubSubDeadLetterSourceDeliveryCount","arbitrary-secret")):
            msg=message()
            msg.attributes[field]=value
            with self.assertRaises(ValueError):inspect_message(msg,PROJECT,NUMBER)

    def test_poison99_is_inspected_without_republishing_or_changing_original_bytes(self):
        normal=inspect_message(message(),PROJECT,NUMBER)
        poison=message(99)
        original=bytes(poison.data)
        result=inspect_message(poison,PROJECT,NUMBER)
        self.assertEqual(result["canonical_sha256"],normal["canonical_sha256"])
        self.assertNotEqual(result["data_sha256"],normal["data_sha256"])
        self.assertNotEqual(result["source_digest"],normal["source_digest"])
        self.assertEqual(bytes(poison.data),original)
        self.client.publish.assert_not_called()

    def test_unknown_fields_formats_json_duplicates_depth_and_bounds_are_held(self):
        invalid=[message(2),message(owner="alice")]
        for body in (b"x"*4097,b'{"schema_version":1,"schema_version":99}',b'{"nested":'+b'['*12+b'0'+b']'*12+b'}'):
            msg=message()
            msg.data=body
            invalid.append(msg)
        for msg in invalid:
            self.client.pull.return_value=PullResponse(received_messages=[ReceivedMessage(message=msg,ack_id="private")])
            receipts,held=self.dead.inspect()
            self.assertEqual((receipts,held),([],1))
        self.client.acknowledge.assert_not_called()

    def test_sdk_ack_waits_for_terminal_binding_and_audit_then_uses_one_current_token(self):
        result=self.dead.acknowledge(receipt(),self.verify,self.approve)
        self.verify.assert_called_once_with(EVENT)
        self.approve.assert_called_once_with(EVENT,receipt().summary["source_digest"])
        call=self.client.acknowledge.call_args
        self.assertIsInstance(call.kwargs["request"],AcknowledgeRequest)
        self.assertEqual((call.kwargs["request"].subscription,list(call.kwargs["request"].ack_ids)),(SUB,["private-ack-token"]))
        self.assertEqual((call.kwargs["retry"],call.kwargs["timeout"]),(None,5))
        self.assertEqual((result["ack_request"],result["absence_verified"]),("accepted",False))
        self.assertNotIn("private-ack-token",json.dumps(result))

    def test_accepted_published_or_mismatched_bindings_never_ack_or_approve(self):
        for field,value in (("terminal_verified",False),("terminal_verified","true"),
            ("order_state","accepted"),("event_id","d"*32),("order_id","d"*32),
            ("order_fingerprint","d"*64),("payload_sha256","d"*64)):
            self.verify.return_value={**proof(),field:value}
            with self.assertRaisesRegex(ValueError,"terminal_binding_not_verified"):
                self.dead.acknowledge(receipt(),self.verify,self.approve)
        self.approve.assert_not_called()
        self.client.acknowledge.assert_not_called()

    def test_unconfirmed_nonterminal_audit_does_not_ack(self):
        for field,value in (("outcome","prepared"),("event_id","d"*32),
            ("source_digest","e"*64),("epoch",True),("replayed","true")):
            self.approve.return_value={**approval(),field:value}
            with self.assertRaisesRegex(ValueError,"terminal_audit_not_confirmed"):
                self.dead.acknowledge(receipt(),self.verify,self.approve)
        self.approve.side_effect=TimeoutError("private-secret")
        with self.assertRaises(TimeoutError):
            self.dead.acknowledge(receipt(),self.verify,self.approve)
        self.client.acknowledge.assert_not_called()

    def test_stale_future_or_corrupted_receipt_is_not_used(self):
        for pulled_at in (NOW-91,NOW+1):
            bad=Receipt(receipt().summary,"private-ack-token",pulled_at)
            with self.assertRaisesRegex(ValueError,"receipt_expired"):
                self.dead.acknowledge(bad,self.verify,self.approve)
        bad=copy.deepcopy(receipt().private_value())
        bad["summary"]["order_id"]="f"*32
        with self.assertRaisesRegex(ValueError,"receipt_digest"):
            Receipt.load(bad,PROJECT,NUMBER)
        for time in (float("nan"),True):
            bad=receipt().private_value()
            bad["pulled_at"]=time
            with self.assertRaises(ValueError):Receipt.load(bad,PROJECT,NUMBER)
        self.client.acknowledge.assert_not_called()

    def test_receipt_expiring_during_verification_prevents_audit_and_ack(self):
        now=[NOW]
        dead=DeadLetters(self.client,PROJECT,NUMBER,clock=lambda:now[0])
        def verify(_):
            now[0]+=91
            return proof()
        with self.assertRaisesRegex(ValueError,"receipt_expired"):
            dead.acknowledge(receipt(),verify,self.approve)
        self.approve.assert_not_called()
        self.client.acknowledge.assert_not_called()

    def test_ack_or_pull_rpc_unknown_outcome_is_sanitized_without_retries(self):
        self.client.acknowledge.side_effect=TimeoutError("private-token-secret")
        with self.assertRaisesRegex(ValueError,"ack_unconfirmed_repull_and_reconcile") as error:
            self.dead.acknowledge(receipt(),self.verify,self.approve)
        self.assertNotIn("private-token-secret",str(error.exception))
        self.client.acknowledge.assert_called_once()
        self.client.pull.side_effect=RuntimeError("private-token-secret")
        with self.assertRaisesRegex(ValueError,"inspect_unconfirmed_no_ack"):
            self.dead.inspect()

    def test_more_than_five_or_missing_ack_token_is_not_accepted(self):
        self.client.pull.return_value=PullResponse(received_messages=[
            ReceivedMessage(message=message(),ack_id="private") for _ in range(6)])
        with self.assertRaisesRegex(ValueError,"too_many_messages"):
            self.dead.inspect()
        self.client.pull.return_value=PullResponse(received_messages=[ReceivedMessage(message=message())])
        self.assertEqual(self.dead.inspect(),([],1))
        self.client.acknowledge.assert_not_called()

    def test_sdk_real_installed_client_receives_expected_contract_without_network(self):
        client=SubscriberClient(credentials=AnonymousCredentials())
        try:
            pull_method=client._transport.pull
            ack_method=client._transport.acknowledge
            pull=Mock(return_value=PullResponse(received_messages=[
                ReceivedMessage(message=message(),ack_id="private-ack-token")]))
            ack=Mock(return_value=Empty())
            client._transport._wrapped_methods[pull_method]=pull
            client._transport._wrapped_methods[ack_method]=ack
            dead=DeadLetters(client,PROJECT,NUMBER,clock=lambda:NOW)
            receipts,held=dead.inspect()
            self.assertEqual(held,0)
            dead.acknowledge(receipts[0],self.verify,self.approve)
            self.assertEqual(pull.call_args.args[0].max_messages,5)
            self.assertEqual(pull.call_args.kwargs["timeout"],10)
            self.assertIsNone(ack.call_args.kwargs["retry"])
            self.assertEqual(ack.call_args.kwargs["timeout"],5)
        finally:
            client.transport.close()

    def test_receipts_private_no_overwrite_and_public_summary_has_no_ack_token(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"pull-1"
            summaries=cli.write_receipts(target,[receipt()])
            self.assertNotIn("private-ack-token",json.dumps(summaries))
            path=target/summaries[0]["receipt_file"]
            self.assertEqual(Receipt.load(cli.operator.private_read(path,16384),PROJECT,NUMBER).ack_id,"private-ack-token")
            if os.name=="posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o700)
            before=path.read_bytes()
            with self.assertRaises(FileExistsError):cli.write_receipts(target,[receipt()])
            self.assertEqual(before,path.read_bytes())

    def test_build_validates_identity_and_config_before_adc_or_rpc(self):
        with patch.object(cli,"SubscriberClient") as client:
            with self.assertRaises(ValueError):cli.build("bad","not-number")
            with patch.dict(os.environ,{"PUBSUB_EMULATOR_HOST":"private-secret"},clear=True):
                with self.assertRaises(ValueError):cli.build(PROJECT,NUMBER)
            client.assert_not_called()

    def test_cli_existing_destination_refuses_before_leasing_and_sanitizes_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output=io.StringIO()
            args=["dead-letter.py","--project",PROJECT,"--project-number",NUMBER,"inspect","--out",folder]
            with patch.object(sys,"argv",args),patch.object(cli,"build") as build,patch("sys.stdout",output):
                self.assertEqual(cli.main(),2)
                build.assert_not_called()
            self.assertNotIn("ack_id",output.getvalue())
            self.assertIn("do_not_create_new_order",output.getvalue())


if __name__=="__main__":
    unittest.main()
