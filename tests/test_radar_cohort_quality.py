"""Regression checks for distinguishing selection turnover and data degradation."""
import unittest
from radar_cohort_quality import compare

class CohortTests(unittest.TestCase):
    def test_turnover_not_degradation(self):
        prev={"1":{"id":"1","symbol":"AAA","data_status":"COMPLETE"},
              "2":{"id":"2","symbol":"BBB","data_status":"COMPLETE"},
              "3":{"id":"3","symbol":"CCC","data_status":"PARTIAL HISTORY"}}
        curr={"1":{"id":"1","symbol":"AAA","data_status":"COMPLETE"},
              "3":{"id":"3","symbol":"CCC","data_status":"PARTIAL HISTORY"},
              "4":{"id":"4","symbol":"DDD","data_status":"INSUFFICIENT DATA"}}
        a=compare(prev,curr)
        self.assertEqual(a["entered"],1)
        self.assertEqual(a["exited"],1)
        self.assertEqual(a["same_asset_complete_to_incomplete"],0)
        self.assertEqual(a["prior_status_counts"]["COMPLETE"],2)
        self.assertEqual(a["current_status_counts"]["COMPLETE"],1)

    def test_true_regression_is_counted(self):
        p={"1":{"id":"1","symbol":"AAA","data_status":"COMPLETE"}}
        q={"1":{"id":"1","symbol":"AAA","data_status":"PARTIAL HISTORY"}}
        a=compare(p,q)
        self.assertEqual(a["same_asset_complete_to_incomplete"],1)
        self.assertEqual(a["entered"],0)
        self.assertEqual(a["exited"],0)

if __name__=="__main__":unittest.main()
