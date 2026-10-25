from pathlib import Path
import sys
import unittest

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
from order_domain import Rejected,canonical
from replay import replay_request


class ReplayRequestTests(unittest.TestCase):
    def body(self):
        return {"idempotency_key":"a"*32,"source_digest":"b"*64,"reason":"dependency_restored"}

    def test_exact_bounded_contract_has_no_replacement_payload(self):
        valid=self.body()
        self.assertEqual(replay_request(canonical(valid)),valid)
        for extra in ("owner","payload","items","topic","operator"):
            with self.assertRaises(Rejected):
                replay_request(canonical({**valid,extra:"attacker-controlled"}))
        for mutate in (lambda v:v.update(idempotency_key="bad"),
            lambda v:v.update(source_digest="x"*65),lambda v:v.update(reason="free text"),
            lambda v:v.update(reason=[]),lambda v:v.pop("reason")):
            value=self.body()
            mutate(value)
            with self.assertRaises(Rejected):
                replay_request(canonical(value))

    def test_duplicate_fields_and_oversized_request_are_rejected(self):
        for value in (b'{"reason":"x","reason":"y"}',b"x"*4097):
            with self.assertRaises(Rejected):
                replay_request(value)


if __name__=="__main__":
    unittest.main()
