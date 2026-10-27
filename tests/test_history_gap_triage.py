import unittest
from history_gap_triage import triage


class HistoryGapTriageTests(unittest.TestCase):
    def test_classification_and_no_synthetic_values(self):
        rows = [
            {"history_selection": "ANALYZED", "data_status": "PARTIAL HISTORY", "id": "1", "symbol": "AAA", "history_missing_fields": '{"spam": 4}'},
            {"history_selection": "ANALYZED", "data_status": "INSUFFICIENT DATA", "id": "2", "symbol": "BBB", "history_missing_fields": '{"close": 3, "sentiment": 2}'},
            {"history_selection": "ANALYZED", "data_status": "INSUFFICIENT DATA", "id": "3", "symbol": "CCC", "history_error": "TimeoutError", "history_missing_fields": "{}"},
            {"history_selection": "ANALYZED", "data_status": "COMPLETE", "id": "4", "symbol": "DDD"},
            {"history_selection": "OUTSIDE HISTORY BUDGET", "data_status": "NOT ANALYZED", "id": "5", "symbol": "EEE"},
        ]
        result = triage(rows)
        self.assertEqual(result["incomplete_candidates"], 3)
        self.assertEqual(result["issue_categories"]["FETCH ERROR"], 1)
        self.assertEqual(result["issue_categories"]["MISSING DAILY BARS"], 1)
        self.assertEqual(result["issue_categories"]["PROVIDER FIELD GAPS"], 1)
        self.assertEqual(result["affected_assets_by_field"]["spam"], 1)


if __name__ == "__main__":
    unittest.main()
