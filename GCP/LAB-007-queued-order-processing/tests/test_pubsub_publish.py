import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from google.auth.credentials import AnonymousCredentials
from google.pubsub_v1.services.publisher import PublisherClient
from google.pubsub_v1.types import PublishResponse

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
from order_domain import event_bytes
from pubsub_publish import Publisher, UnconfirmedPublish, build_publisher

BODY=event_bytes("a"*32,"b"*32,"c"*64)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.client=PublisherClient(credentials=AnonymousCredentials())
        self.addCleanup(self.client.transport.close)
        self.publisher=Publisher(self.client,"demo-lab007")

    def test_real_request_proto_single_message_and_rpc_bounds(self):
        with patch.object(self.client,"publish",autospec=True,
                          return_value=PublishResponse(message_ids=["123456"])) as publish:
            self.assertEqual(self.publisher.publish(BODY),"123456")
            call=publish.call_args.kwargs
            self.assertIsNone(call["retry"])
            self.assertEqual(call["timeout"],5.0)
            self.assertEqual(call["request"].topic,"projects/demo-lab007/topics/lab007-orders")
            self.assertEqual(len(call["request"].messages),1)
            self.assertEqual(call["request"].messages[0].data,BODY)
            self.assertEqual(dict(call["request"].messages[0].attributes),{})

    def test_rpc_failure_and_malformed_ack_remain_unknown(self):
        for response in [PublishResponse(),PublishResponse(message_ids=["1","2"]),
                         PublishResponse(message_ids=["private token"])]:
            with patch.object(self.client,"publish",autospec=True,return_value=response):
                with self.assertRaisesRegex(UnconfirmedPublish,"^publish_unconfirmed$"):
                    self.publisher.publish(BODY)
        with patch.object(self.client,"publish",autospec=True,
                          side_effect=RuntimeError("private-secret")):
            with self.assertRaises(UnconfirmedPublish) as error:
                self.publisher.publish(BODY)
            self.assertNotIn("private-secret",str(error.exception))

    def test_noncanonical_payload_is_rejected_without_rpc(self):
        with patch.object(self.client,"publish",autospec=True) as publish:
            with self.assertRaisesRegex(ValueError,"noncanonical_event"):
                self.publisher.publish(BODY+b" ")
            publish.assert_not_called()

    def test_runtime_rejects_emulator_and_keyfile(self):
        for key in ["PUBSUB_EMULATOR_HOST","GOOGLE_APPLICATION_CREDENTIALS"]:
            with patch.dict(os.environ,{key:"forbidden"}):
                with self.assertRaisesRegex(ValueError,"attached_identity_required"):
                    build_publisher("demo-lab007")

    def test_invalid_project_is_not_a_destination_override(self):
        for project in ["", "other/project", "https://attacker.example", True]:
            with self.assertRaises(ValueError):
                Publisher(self.client,project)


if __name__=="__main__":
    unittest.main()
