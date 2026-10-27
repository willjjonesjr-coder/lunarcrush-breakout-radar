import json
import tempfile
import unittest
from pathlib import Path
from production_readiness import audit


class ReadinessTests(unittest.TestCase):
    def test_missing_days_not_treated_as_zero(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports = Path(root) / "data", Path(root) / "reports"
            data.mkdir()
            reports.mkdir()
            (data / "volume_snapshot_history.json").write_text(json.dumps({"2026-10-26": {"BTC": 10}}))
            (reports / "radar_coverage.json").write_text(json.dumps({
                "history_candidates": 300, "data_status_counts": {"COMPLETE": 162, "PARTIAL HISTORY": 81, "INSUFFICIENT DATA": 57}
            }))
            result = audit(data, reports, "2026-10-27")
            self.assertFalse(result["baseline"]["ready"])
            self.assertEqual(len(result["baseline"]["missing_dates"]), 6)
            self.assertEqual(result["history"]["complete_pct"], 54.0)

    def test_seven_days_can_be_ready(self):
        with tempfile.TemporaryDirectory() as root:
            data, reports = Path(root) / "data", Path(root) / "reports"
            data.mkdir()
            reports.mkdir()
            from datetime import date, timedelta
            history = {(date(2026, 10, 27) - timedelta(days=i)).isoformat(): {"BTC": 10}
                       for i in range(1, 8)}
            (data / "volume_snapshot_history.json").write_text(json.dumps(history))
            self.assertTrue(audit(data, reports, "2026-10-27")["baseline"]["ready"])


if __name__ == "__main__":
    unittest.main()
