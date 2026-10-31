"""Regression tests for EMA inventory coverage and fail-closed technical checks."""
import csv
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import ema_inventory_coverage
from phase2_safeguards import technical_confirmation, resolve_ema_source


class EMACoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reports = self.root / "reports"
        self.reports.mkdir()
        (self.root / "data_price").mkdir()
        self.today = date(2026, 10, 31)
        self.write_radar(["11", "169"])

    def write_radar(self, ids):
        with (self.reports / "breakout_radar.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "technical_status"])
            w.writeheader()
            w.writerows({"id": i, "technical_status": "EMA NOT CONFIRMED"} for i in ids)

    def write_freshness(self, eligible=True):
        data = {"assets": [
            {"coin_id": i, "exchange": "kraken", "pair": p,
             "eligible": eligible, "latest_candle": "2026-10-30",
             "blocker": None if eligible else "STALE LAST COMPLETED CANDLE"}
            for i, p in (("11", "ADA/USD"), ("169", "FET/USD"))]}
        (self.reports / "ema_freshness_audit.json").write_text(json.dumps(data))

    def test_turnover_does_not_change_verified_inventory(self):
        self.write_freshness()
        with patch.object(ema_inventory_coverage, "ROOT", self.root), patch.object(
            ema_inventory_coverage, "REPORTS", self.reports), patch.object(
            ema_inventory_coverage, "technical_confirmation",
            return_value={"technical_status": "EMA NOT CONFIRMED"}):
            before = ema_inventory_coverage.generate(self.today)
            self.write_radar(["11"])
            after = ema_inventory_coverage.generate(self.today)
        self.assertEqual((before["verified_inventory_records"], after["verified_inventory_records"]), (2, 2))
        self.assertEqual((before["fresh_eligible_inventory"], after["fresh_eligible_inventory"]), (2, 2))
        self.assertEqual((before["ema_evaluable_in_current_300"], after["ema_evaluable_in_current_300"]), (2, 1))
        self.assertEqual(after["off_universe_fresh_eligible"], 1)
        self.assertEqual(after["off_universe_technical_confirmed"], 0)

    def test_stale_asset_does_not_get_off_universe_evaluation(self):
        self.write_radar([])
        self.write_freshness(False)
        with patch.object(ema_inventory_coverage, "ROOT", self.root), patch.object(
            ema_inventory_coverage, "REPORTS", self.reports), patch.object(
            ema_inventory_coverage, "technical_confirmation") as technical:
            report = ema_inventory_coverage.generate(self.today)
        technical.assert_not_called()
        self.assertEqual(report["fresh_eligible_inventory"], 0)
        self.assertEqual(report["off_universe_fresh_eligible"], 0)

    def test_stale_and_gap_candles_fail_closed(self):
        p = self.root / "data_price" / "11.csv"
        def write(days):
            with p.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["time", "close"])
                writer.writeheader()
                writer.writerows({"time": d.isoformat() + "T00:00:00Z", "close": 1.0} for d in days)
        days = [self.today - timedelta(days=i) for i in range(1, 301)]
        write(days[1:])
        self.assertEqual(technical_confirmation(p, self.today)["technical_status"], "INSUFFICIENT EMA HISTORY")
        write([d for d in days if d != days[120]])
        self.assertEqual(technical_confirmation(p, self.today)["technical_status"], "INSUFFICIENT EMA HISTORY")
        write(days)
        self.assertIn(technical_confirmation(p, self.today)["technical_status"], ("EMA CONFIRMED", "EMA NOT CONFIRMED"))

    def test_invalid_mapping_does_not_use_exchange_prices(self):
        mapping = self.root / "symbol_map.json"
        mapping.write_text(json.dumps({"11": {"exchange": "kraken", "pair": "FAKE/USD"}}))
        inventory = self.reports / "backfill_inventory.csv"
        with inventory.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["coin_id", "exchange", "pair", "status", "gaps_detected"])
            w.writeheader()
            w.writerow({"coin_id": "11", "exchange": "kraken", "pair": "ADA/USD", "status": "ok", "gaps_detected": "0"})
        p = self.root / "data_price" / "11.csv"
        p.write_text("time,close,exchange,pair\\n2026-10-30T00:00:00Z,1,kraken,ADA/USD\\n".replace("\\n", "\n"))
        native, source = resolve_ema_source("11", self.root, self.root / "data_price", mapping, inventory)
        self.assertEqual(source, "LUNARCRUSH HISTORY")
        self.assertEqual(native, self.root / "history_11.csv")


if __name__ == "__main__":
    unittest.main()
