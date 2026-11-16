"""Offline regression tests for conservative price-corroborated EMA research."""
import csv
import json
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from tools.research_price_corroborated_ema import (
    evaluate_prices, parse_sources, reference_history, known_conflict, write_report
)


class PriceCorroborationTests(unittest.TestCase):
    @staticmethod
    def histories(n=5, start=date(2026, 11, 10)):
        return {start + timedelta(days=i): 1.0 + i * 0.01 for i in range(n)}

    def test_three_exact_utc_days_within_two_percent(self):
        ref = self.histories()
        src = {day: price * 1.01 for day, price in ref.items()}
        r = evaluate_prices(ref, src, date(2026, 11, 14))
        self.assertEqual(r["status"], "PRICE_CORROBORATED")
        self.assertEqual(len(r["checks"]), 5)
        self.assertAlmostEqual(r["max_pct"], 1.0)

    def test_tolerance_exceeded_fails_even_if_average_small(self):
        ref = self.histories()
        src = dict(ref)
        src[date(2026, 11, 12)] *= 1.03
        r = evaluate_prices(ref, src, date(2026, 11, 14))
        self.assertEqual(r["status"], "PRICE_MISMATCH")

    def test_requires_three_consecutive_same_utc_days(self):
        ref = self.histories()
        src = {d: p for d,p in ref.items() if d != date(2026, 11, 13)}
        r = evaluate_prices(ref, src, date(2026, 11, 14))
        self.assertEqual(r["status"], "INSUFFICIENT_ALIGNED_DATA")
        self.assertNotIn("checks", r)

    def test_not_latest_day_is_not_corroboration(self):
        ref = self.histories()
        r = evaluate_prices(ref, {d:p for d,p in ref.items() if d < date(2026, 11, 14)},
                            date(2026, 11, 14))
        self.assertEqual(r["status"], "INSUFFICIENT_ALIGNED_DATA")

    def test_flat_series_is_not_strong_identity_evidence(self):
        ref = {d: 1.0 for d in self.histories()}
        r = evaluate_prices(ref, dict(ref), date(2026, 11, 14))
        self.assertEqual(r["status"], "LOW_INFORMATION")

    def test_coin_symbol_and_derivative_pair_must_match(self):
        row = {"symbol": "TOP", "source_markets": "mexc:TOP/USDT;gate:TOP/USDT:USDT;okx:OTHER/USDT"}
        self.assertEqual(parse_sources(row), [("mexc", "TOP/USDT")])

    def test_known_conflict_blocks(self):
        self.assertTrue(known_conflict({"coin_id":"17"}, {"17":"contract mismatch"}))

    def test_reference_rejects_wrong_coin_id(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.csv"
            with path.open("w", newline="") as f:
                w=csv.writer(f); w.writerow(("time", "close", "coin_id"))
                w.writerow(("2026-11-14 00:00:00+00:00", "0.001", "999"))
            with self.assertRaisesRegex(ValueError, "conflicts"):
                reference_history(path, "157816")

    def test_end_to_end_research_does_not_approve_or_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            history = p / "history"
            history.mkdir()
            start=date(2026,11,10)
            with (history / "history_157816.csv").open("w",newline="") as f:
                w=csv.writer(f); w.writerow(("time", "close", "coin_id"))
                for i in range(5):
                    d=start+timedelta(days=i)
                    w.writerow((d.isoformat()+" 00:00:00+00:00",1+i/100,"157816"))
            ready=p/"input.csv"
            with ready.open("w",newline="") as f:
                w=csv.DictWriter(f,fieldnames=["coin_id","symbol","name","source_markets"])
                w.writeheader(); w.writerow({"coin_id":"157816","symbol":"TOP","name":"TOP AI Network",
                                            "source_markets":"mexc:TOP/USDT"})
            class Exchange:
                def load_markets(self): pass
            mock_ccxt=types.ModuleType("ccxt")
            mock_ccxt.mexc=lambda cfg:Exchange()
            candles=[]
            for i in range(500):
                d=date(2025,7,3)+timedelta(days=i)
                # Last five days are 2026-11-10..14
                close=(1+(i-495)/100) if i>=495 else 0.9
                candles.append([d.isoformat()+"T00:00:00Z",close,close,close,close,100])
            # Use last five exact closes from local history.
            with patch.dict(sys.modules, {"ccxt":mock_ccxt}), \\
                 patch("tools.research_price_corroborated_ema.fetch_history",return_value=candles), \\
                 patch("tools.research_price_corroborated_ema.provisional_technicals",
                       return_value={"provisional_technical_status":"PROVISIONAL EMA ALIGNED",
                         "provisional_ema50":1.0,"provisional_ema100":0.9,"provisional_ema200":0.8}):
                result=write_report(ready,history,p/"out",today=date(2026,11,15))
            self.assertEqual(result["fully_verified"],0)
            self.assertEqual(result["production_approvals"],0)
            self.assertEqual(result["alerts"],0)
            # The 500 day synthetic sequence must end on Nov 14.
            self.assertEqual(result["corroborated"],1)
            row=list(csv.DictReader(open(p/"out"/"price_corroboration.csv")))[0]
            self.assertEqual(row["identity_confidence"],"PRICE_CORROBORATED")
            self.assertEqual(row["production_approval"],"NO")
            self.assertEqual(row["alert_eligible"],"NO")
            self.assertTrue(Path(row["research_csv"]).exists())


if __name__ == "__main__":
    unittest.main()
