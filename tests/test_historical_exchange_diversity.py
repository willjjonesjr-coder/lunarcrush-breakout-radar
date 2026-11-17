"""Offline, no-network tests of nine-venue historical research and reporting."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.historical_exchange_diversity import analyze, make_queue


def row(cid, exchange, market="FOUND_PROVISIONAL", history="SHORT_HISTORY", pair="ABC/USDT"):
    return {"coin_id": str(cid), "exchange": exchange, "market_status": market,
            "history_status": history, "pair": pair}


class HistoricalDiversityTests(unittest.TestCase):
    def test_uses_same_ids_and_rank_as_legacy_backfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            radar = Path(tmp) / "radar.csv"
            with radar.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["id", "symbol", "name"])
                w.writeheader()
                w.writerows([{"id": "7", "symbol": "AAA", "name": "Alpha"},
                             {"id": "2", "symbol": "BBB", "name": "Beta"}])
            with patch("tools.historical_exchange_diversity.universe", return_value=["2", "7"]) as legacy:
                queue = make_queue(tmp, 2, radar)
            legacy.assert_called_once_with(tmp, 2)
            self.assertEqual([r["coin_id"] for r in queue], ["2", "7"])
            self.assertEqual([r["review_rank"] for r in queue], [1, 2])
            self.assertEqual([r["symbol"] for r in queue], ["BBB", "AAA"])
            with self.assertRaises(ValueError):
                make_queue(tmp, 81, radar)

    def test_incremental_coverage_and_unique_coins_not_market_rows(self):
        rows = [
            row(1, "kraken", history="500_BAR_READY_PROVISIONAL"),
            row(1, "mexc", history="500_BAR_READY_PROVISIONAL"),
            row(1, "mexc", history="500_BAR_READY_PROVISIONAL", pair="ABC/USDC"),
            row(2, "kraken", market="NO_EXACT_SPOT_PAIR", history="NOT_CHECKED"),
            row(2, "gate", history="500_BAR_READY_PROVISIONAL"),
            row(3, "coinbase", history="300_BAR_READY_PROVISIONAL"),
            row(3, "okx", history="500_BAR_READY_PROVISIONAL"),
            row(4, "bybit", market="EXCHANGE_UNAVAILABLE", history="NOT_CHECKED"),
        ]
        legacy = [{"coin_id": "1", "status": "ok", "exchange": "kraken"},
                  {"coin_id": "2", "status": "unresolved", "exchange": ""},
                  {"coin_id": "3", "status": "partial", "exchange": "coinbase"},
                  {"coin_id": "4", "status": "unresolved", "exchange": ""}]
        by_exchange, summary = analyze(rows, legacy)
        lookup = {r["exchange"]: r for r in by_exchange}
        self.assertEqual(len(by_exchange), 9)
        self.assertEqual(lookup["mexc"]["history_500_coins"], 1)
        self.assertEqual(lookup["gate"]["history_500_coins"], 1)
        self.assertEqual(lookup["bybit"]["unavailable_coins"], 1)
        self.assertEqual(summary["research_300_plus_unique_coins"], 3)
        self.assertEqual(summary["research_500_unique_coins"], 3)
        self.assertEqual(summary["incremental_300_plus_unique_coins_vs_original_three"], 1)
        self.assertEqual(summary["incremental_500_unique_coins_vs_original_three"], 2)
        self.assertEqual(summary["legacy_selected_exchange_counts"], {"kraken": 1, "coinbase": 1})
        self.assertEqual(summary["identity_approvals"], 0)
        self.assertEqual(summary["production_imports"], 0)

    def test_unavailable_does_not_mean_no_market_or_approval(self):
        rows = [row(9, "binance", "EXCHANGE_UNAVAILABLE", "NOT_CHECKED"),
                row(9, "mexc", "FOUND_PROVISIONAL", "SHORT_HISTORY")]
        per_exchange, summary = analyze(rows, [])
        self.assertIn("binance", summary["venues_unavailable"])
        self.assertEqual(summary["research_300_plus_unique_coins"], 0)
        self.assertEqual(per_exchange[0]["identity_status"], "UNVERIFIED_RESEARCH_ONLY")
        self.assertTrue(all(r["production_approvals"] == 0 for r in per_exchange))


if __name__ == "__main__":
    unittest.main()
