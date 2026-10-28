import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from phase2_safeguards import by_id, vetted_sector_segments, technical_confirmation, notification_readiness


class Phase2Tests(unittest.TestCase):
    def test_sector_coins_are_id_keyed_not_symbol_keyed(self):
        rows = [{"id": "123", "symbol": "ABC", "volume_24h": 300},
                {"id": "456", "symbol": "ABC", "volume_24h": 400}]
        snap = by_id(rows)
        self.assertEqual(vetted_sector_segments(snap, {"DeFi": ["123"]})["DeFi"], {"123": 300})
        self.assertEqual(vetted_sector_segments(snap, {"DeFi": []})["DeFi"], {})
        with self.assertRaises(ValueError):
            vetted_sector_segments(snap, {"DeFi": ["123", "123"]})

    def test_ema_uses_only_completed_contiguous_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "history.csv"
            asof = date(2026, 10, 27)
            with file.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["time", "close"])
                writer.writeheader()
                for days_ago in range(300, 0, -1):
                    writer.writerow({"time": (asof - timedelta(days=days_ago)).isoformat(),
                                     "close": 100 + (300-days_ago)*0.3})
                writer.writerow({"time": asof.isoformat(), "close": 999999})
            result = technical_confirmation(file, asof)
            self.assertEqual(result["technical_status"], "EMA CONFIRMED")
            with file.open("r") as f:
                lines = f.readlines()
            file.write_text("".join(lines[:-3]))
            self.assertEqual(technical_confirmation(file, asof)["technical_status"],
                             "INSUFFICIENT EMA HISTORY")

    def test_alert_remains_blocked_without_delivery_configuration(self):
        signal = {"status": "READY", "classification": "EXCEPTIONAL >=3x"}
        self.assertFalse(notification_readiness(signal, True, True)["eligible_for_push"])
        self.assertTrue(notification_readiness(signal, True, True)["reasons"])


if __name__ == "__main__":
    unittest.main()
