import unittest
from phase1_monitor import confirmation, evaluate_segment, volume_snapshot


class Phase1MonitorTests(unittest.TestCase):
    def test_duplicate_symbols_excluded_and_zero_volume_preserved(self):
        rows = [{"symbol": "BTC", "volume_24h": "100"},
                {"symbol": "X", "volume_24h": "4"},
                {"symbol": "X", "volume_24h": "6"},
                {"symbol": "ETH", "volume_24h": "0"},
                {"symbol": "BAD", "volume_24h": "nan"}]
        self.assertEqual(volume_snapshot(rows), {"BTC": 100, "ETH": 0})

    def test_only_seven_distinct_days_can_trigger(self):
        now = {"BTC": 300}
        self.assertEqual(evaluate_segment("BTC", now, [{"BTC": 100}] * 6)["status"],
                         "INSUFFICIENT BASELINE")
        x = evaluate_segment("BTC", now, [{"BTC": 100}] * 7)
        self.assertEqual(x["multiple"], 3)
        self.assertEqual(x["classification"], "EXCEPTIONAL >=3x")

    def test_requires_same_cohort_and_coverage(self):
        now = {"A": 80, "B": 20, "C": 10}
        prior = [{"A": 40, "B": 20, "C": 10}] * 6 + [{"A": 40, "B": 20}]
        self.assertEqual(evaluate_segment("DeFi basket", now, prior)["status"],
                         "INSUFFICIENT COVERAGE")
        self.assertEqual(evaluate_segment("DeFi basket", now, [{"A": 40, "B": 20, "C": 10}] * 7)["status"], "READY")

    def test_strong_label_requires_independent_evidence(self):
        good = {"breakout_score": 66, "volume_daily_accel": 2,
                "engagement_daily_accel": 1, "social_accel": .8,
                "contributor_accel": .4, "price_change_7d": .08,
                "volume_24h_snapshot": 9_000_000, "extension_penalty": 2,
                "spam_penalty": 0, "data_status": "COMPLETE"}
        label, caution = confirmation(good)
        self.assertIn("MULTI-SIGNAL", label)
        self.assertEqual(caution, "")
        weak = {**good, "volume_daily_accel": -.3}
        self.assertEqual(confirmation(weak)[0], "UNCONFIRMED")
        illiquid = {**good, "volume_24h_snapshot": 100_000}
        self.assertEqual(confirmation(illiquid)[0], "HIGH RISK / UNCONFIRMED")


if __name__ == "__main__":
    unittest.main()
