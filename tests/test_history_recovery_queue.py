import unittest
from history_recovery_queue import queue


class RecoveryQueueTests(unittest.TestCase):
    def test_ordering_and_no_auto_retries(self):
        rows = [
            {"history_selection": "ANALYZED", "data_status": "PARTIAL HISTORY",
             "id": "2", "symbol": "LOW", "snapshot_score": "70", "history_missing_fields": '{"spam": 2}'},
            {"history_selection": "ANALYZED", "data_status": "PARTIAL HISTORY",
             "id": "1", "symbol": "HIGH", "snapshot_score": "90", "history_missing_fields": '{"close": 1}'},
            {"history_selection": "ANALYZED", "data_status": "COMPLETE",
             "id": "3", "symbol": "OK", "snapshot_score": "100"},
        ]
        report = queue(rows, limit=1)
        self.assertEqual(report["total_incomplete"], 2)
        self.assertEqual(report["review_first"][0]["symbol"], "HIGH")
        self.assertEqual(len(report["all_incomplete"]), 2)
        self.assertIn("Do not request retries automatically", report["policy"])


if __name__ == "__main__":
    unittest.main()
