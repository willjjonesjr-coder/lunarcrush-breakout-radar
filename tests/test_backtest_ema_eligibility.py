import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tools.backtest_ema_eligibility import audit


class EmaBacktestEligibilityAuditTests(unittest.TestCase):
    def test_distinguishes_short_inputs_from_ema200_eligible_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for coin, count in (("short", 90), ("long", 220)):
                pd.DataFrame({
                    "time": pd.date_range("2024-01-01", periods=count, tz="UTC"),
                    "close": [100.0] * count,
                }).to_csv(directory / f"history_{coin}.csv", index=False)
            result = audit(directory)
            self.assertEqual(result["histories_loaded"], 2)
            self.assertEqual(result["at_least_50_rows"], 2)
            self.assertEqual(result["at_least_100_rows"], 1)
            self.assertEqual(result["at_least_200_rows"], 1)
            self.assertEqual(result["ema200_evaluable_histories"], 1)
            self.assertEqual(result["ema200_not_evaluable_histories"], 1)
            self.assertEqual(result["status"], "eligible_histories_present")

    def test_reports_unavailable_not_bearish_when_all_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            pd.DataFrame({
                "time": pd.date_range("2024-01-01", periods=90, tz="UTC"),
                "close": [1.0] * 90,
            }).to_csv(Path(tmp) / "history_1.csv", index=False)
            result = audit(tmp)
            self.assertEqual(result["ema200_evaluable_histories"], 0)
            self.assertEqual(result["status"], "insufficient_history")


if __name__ == "__main__":
    unittest.main()
