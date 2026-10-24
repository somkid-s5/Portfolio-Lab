import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"reconcile.py"
spec=importlib.util.spec_from_file_location("lab016_reconcile",SCRIPT)
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

class ReconcileContractTests(unittest.TestCase):
 def test_equal_snapshots_pass_all_checks(self):
  value={"count":5,"total_amount_cents":97400,"max_id":1005,"distinct_order_refs":5,
         "by_status":{"NEW":2,"PAID":2,"CANCELLED":1},"sequence_last_value":1005,"sequence_is_called":True}
  self.assertTrue(all(module.compare(value,value).values()))
 def test_business_or_sequence_mismatch_is_never_hidden(self):
  source={"count":5,"total_amount_cents":97400,"max_id":1005,"distinct_order_refs":5,
          "by_status":{"NEW":2,"PAID":2,"CANCELLED":1},"sequence_last_value":1005,"sequence_is_called":True}
  target={**source,"total_amount_cents":97000,"sequence_last_value":1004}
  checks=module.compare(source,target)
  self.assertFalse(checks["total_amount_cents"]); self.assertFalse(checks["sequence_last_value"])
if __name__=="__main__": unittest.main()
