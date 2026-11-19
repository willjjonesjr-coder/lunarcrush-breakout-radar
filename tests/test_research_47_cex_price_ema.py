"""Offline provenance, multi-venue and fail-closed research regression tests."""
import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from tools.build_47_cex_research import reconstruct
from tools.research_47_cex_price_ema import check_candidate


def market(cid, venue, status="500_BAR_READY_PROVISIONAL", symbol="X", name="Example"):
    return dict(coin_id=str(cid), symbol=symbol, name=name, exchange=venue,
                pair="X/USDT", bars_available="500",
                market_status="FOUND_PROVISIONAL", history_status=status,
                identity_status="UNVERIFIED_SYMBOL_MATCH_ONLY",
                approval_status="RESEARCH_ONLY_DO_NOT_IMPORT",
                breakout_score="50")


class CandidateTests(unittest.TestCase):
    def test_incremental_500_only_and_multi_first(self):
        rows = [
            market(1, "kraken", "300_BAR_READY_PROVISIONAL"),
            market(1, "gate"), market(1, "mexc"),
            market(2, "kraken", "SHORT_HISTORY"), market(2, "kucoin"),
        ]
        info = dict(cohort_coins=2,
                    incremental_500_unique_coins_vs_original_three=2,
                    incremental_500_coin_ids=["1", "2"])
        result = reconstruct(info, rows, expected_count=2, expected_cohort=2)
        self.assertEqual(len(result), 2)
        self.assertEqual([r["coin_id"] for r in result], ["1", "2"])
        self.assertEqual([r["source_count"] for r in result], [2, 1])
        self.assertEqual(result[0]["primary_source_markets"], "kraken:X/USDT")
        self.assertEqual([r["priority_group"] for r in result],
                         ["MULTI_EXCHANGE", "SINGLE_EXCHANGE"])
        self.assertTrue(all(r["production_approval"] == "NO" and r["alert_eligible"] == "NO" for r in result))

    def test_existing_original_500_history_is_not_incremental(self):
        info = dict(cohort_coins=1,
                    incremental_500_unique_coins_vs_original_three=1,
                    incremental_500_coin_ids=["1"])
        with self.assertRaisesRegex(ValueError, "not incremental"):
            reconstruct(info, [market(1, "kraken"), market(1, "mexc")],
                        expected_count=1, expected_cohort=1)

    def test_reject_duplicate_missing_or_identity_conflict(self):
        info = dict(cohort_coins=1,
                    incremental_500_unique_coins_vs_original_three=1,
                    incremental_500_coin_ids=["1"])
        with self.assertRaises(ValueError):
            reconstruct({**info, "incremental_500_coin_ids": ["1", "1"]},
                        [market(1, "mexc")], expected_count=1, expected_cohort=1)
        with self.assertRaises(ValueError):
            reconstruct(info, [market(1, "mexc", name="One"),
                                market(1, "gate", name="Other")],
                        expected_count=1, expected_cohort=1)


class PriceResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.today = date(2026, 11, 18)
        self.required = self.today - timedelta(days=1)
        self.closes = {self.required - timedelta(days=i):
                       1.0 + (4-i) * 0.01 for i in range(5)}
        with (self.dir / "history_1.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(("time", "close", "coin_id"))
            for day, value in self.closes.items():
                w.writerow((day.isoformat() + "T00:00:00Z", value, "1"))
        self.item = dict(priority_rank="1", coin_id="1", symbol="X", name="Example",
                         source_count="2", source_markets="gate:X/USDT;mexc:X/USDT")
        self.candles = [[day.isoformat() + "T00:00:00Z", val, val, val, val, 100]
                        for day, val in sorted(self.closes.items())]

    def tearDown(self):
        self.temp.cleanup()

    def evaluate(self, exchange_result=None, conflicts=None):
        with patch("tools.research_47_cex_price_ema.fetch_history",
                   side_effect=exchange_result or [self.candles, self.candles]), \
             patch("tools.research_47_cex_price_ema.provisional_technicals",
                   return_value={"provisional_technical_status": "PROVISIONAL EMA ALIGNED",
                                 "provisional_ema50": 1, "provisional_ema100": 0.9,
                                 "provisional_ema200": 0.8}):
            return check_candidate(self.item, self.dir, lambda _: object(),
                                   self.required, conflicts or {}, 3)

    def test_two_venues_agree_multi_ema_research_only(self):
        result, audit, selected = self.evaluate()
        self.assertEqual(result["corroboration_status"], "PRICE_CORROBORATED_FALLBACK_MULTI_SOURCE")
        self.assertEqual(result["sources_corrob"], 2)
        self.assertEqual(len(audit), 5)
        self.assertEqual(len(audit[3]["comparison_days"].split(";")), 5)
        self.assertEqual(result["production_approval"], "NO")
        self.assertEqual(result["alert_eligible"], "NO")
        self.assertIsNotNone(selected)

    def test_one_good_one_price_mismatch_blocks_ema(self):
        mismatched = [list(c) for c in self.candles]
        mismatched[-1][4] *= 1.05
        result, audit, selected = self.evaluate([self.candles, mismatched])
        self.assertEqual(result["corroboration_status"], "PRICE_CONFLICT_REVIEW")
        self.assertEqual(result["source_disagreements"], 1)
        self.assertEqual(result["ema_status"], "NOT_EVALUATED")
        self.assertIsNone(selected)
        self.assertEqual(audit[-1]["status"], "PRICE_MISMATCH")

    def test_one_available_source_is_not_multisource_confirmation(self):
        result, _, selected = self.evaluate([self.candles, RuntimeError("offline")])
        self.assertEqual(result["corroboration_status"], "INSUFFICIENT_CORROBORATION")
        self.assertIsNone(selected)

    def test_known_conflict_blocks_all_exchange_fetches(self):
        with patch("tools.research_47_cex_price_ema.fetch_history") as fetch:
            result, audit, selected = check_candidate(self.item, self.dir,
                lambda _: object(), self.required, {"1": "wrong contract"})
        fetch.assert_not_called()
        self.assertEqual(result["corroboration_status"], "IDENTITY_CONFLICT")
        self.assertEqual(audit[0]["status"], "IDENTITY_CONFLICT")
        self.assertIsNone(selected)

    def test_single_source_is_separate_research_classification(self):
        self.item.update(source_count="1", source_markets="mexc:X/USDT")
        result, _, selected = self.evaluate([self.candles])
        self.assertEqual(result["corroboration_status"], "PRICE_CORROBORATED_FALLBACK_SINGLE_SOURCE")
        self.assertIsNotNone(selected)


class PrimaryExchangePolicyTests(PriceResearchTests):
    """Validate primary venue priority and two-of-three confirmation policy."""

    @staticmethod
    def technicals():
        return {"provisional_technical_status":"PROVISIONAL EMA ALIGNED",
                "provisional_ema50":1, "provisional_ema100":0.9,
                "provisional_ema200":0.8}

    def test_coinbase_kraken_two_pass_binance_mismatch_does_not_veto(self):
        self.item["primary_source_markets"] = "coinbase:X/USD;kraken:X/USD;binance:X/USDT"
        third = [list(c) for c in self.candles]
        third[-1][4] *= 1.05
        order = []
        def primary(venue, pair, day):
            order.append((venue, 3))
            return third if venue == "binance" else self.candles
        def secondary(venue, pair, day, bars):
            order.append((venue, bars))
            return self.candles
        with patch("tools.research_47_cex_price_ema.fetch_primary_history", side_effect=primary), \
             patch("tools.research_47_cex_price_ema.fetch_history", side_effect=secondary), \
             patch("tools.research_47_cex_price_ema.provisional_technicals",
                   return_value=self.technicals()):
            result, audit, selected = check_candidate(
                self.item, self.dir, lambda venue: venue, self.required, {}, 3)
        self.assertEqual(order, [("coinbase",3),("kraken",3),("binance",3),("gate",500)])
        self.assertEqual(result["corroboration_status"], "PRICE_CORROBORATED_PRIMARY_TWO")
        self.assertEqual(result["primary_venues_corrob"], 2)
        self.assertEqual(result["source_disagreements"], 1)
        self.assertEqual(result["production_approval"], "NO")
        self.assertEqual(result["alert_eligible"], "NO")
        self.assertEqual(audit[2]["status"], "PRICE_MISMATCH")
        self.assertEqual(selected[0], "gate")

    def test_check_all_three_original_venues_before_smaller_sources(self):
        self.item["primary_source_markets"] = "coinbase:X/USD;kraken:X/USD;binance:X/USDT"
        seen = []
        def primary(venue, pair, day):
            seen.append(venue)
            return self.candles
        def secondary(venue, pair, day, bars):
            seen.append(venue)
            return self.candles
        with patch("tools.research_47_cex_price_ema.fetch_primary_history", side_effect=primary), \
             patch("tools.research_47_cex_price_ema.fetch_history", side_effect=secondary), \
             patch("tools.research_47_cex_price_ema.provisional_technicals",
                   return_value=self.technicals()):
            result, audit, _ = check_candidate(
                self.item, self.dir, lambda venue: venue, self.required, {}, 3)
        self.assertEqual(seen, ["coinbase","kraken","binance","gate"])
        self.assertEqual(result["primary_venues_checked"], 3)
        self.assertEqual(result["primary_venues_corrob"], 3)
        self.assertEqual([a["exchange"] for a in audit[:3]], list(("coinbase","kraken","binance")))

    def test_two_primary_agree_but_no_500_bar_source_withholds_ema(self):
        self.item["primary_source_markets"] = "coinbase:X/USD;kraken:X/USD"
        with patch("tools.research_47_cex_price_ema.fetch_primary_history",
                   return_value=self.candles), \
             patch("tools.research_47_cex_price_ema.fetch_history",
                   side_effect=RuntimeError("no 500 bars")):
            result, _, selected = check_candidate(
                self.item, self.dir, lambda venue: venue, self.required, {}, 3)
        self.assertEqual(result["corroboration_status"], "PRICE_CORROBORATED_PRIMARY_TWO")
        self.assertEqual(result["ema_status"], "NOT_EVALUATED")
        self.assertIsNone(selected)

    def test_known_identity_conflict_prevents_all_exchange_fetches(self):
        self.item["primary_source_markets"] = "coinbase:X/USD;kraken:X/USD"
        with patch("tools.research_47_cex_price_ema.fetch_history") as secondary, \
             patch("tools.research_47_cex_price_ema.fetch_primary_history") as primary:
            result, _, selected = check_candidate(
                self.item, self.dir, lambda _: object(), self.required,
                {"1":"wrong contract"})
        secondary.assert_not_called()
        primary.assert_not_called()
        self.assertEqual(result["corroboration_status"], "IDENTITY_CONFLICT")
        self.assertIsNone(selected)

    def test_primary_source_parser_rejects_wrong_base_or_derivatives(self):
        from tools.research_47_cex_price_ema import primary_sources
        item = {"symbol":"X", "primary_source_markets":
                "coinbase:OTHER/USD;kraken:X/USDT:USDT;binance:X/USDT;coinbase:X/USD"}
        self.assertEqual(primary_sources(item), {"coinbase":"X/USD","binance":"X/USDT"})

    def test_primary_three_day_candles_do_not_need_300_bars(self):
        from datetime import datetime, timezone
        from tools.research_47_cex_price_ema import fetch_primary_history
        class Client:
            markets = {"X/USD":{"spot":True,"active":True,"base":"X","quote":"USD"}}
            has = {"fetchOHLCV": True}
            def fetch_ohlcv(self, *args, **kwargs):
                rows = []
                for i in range(3):
                    day = date(2026,11,15) + timedelta(days=i)
                    ms = int(datetime.combine(day, datetime.min.time(), timezone.utc).timestamp()*1000)
                    rows.append([ms, 1, 2, 0.5, 1.5 + i*0.01, 100])
                return rows
        result = fetch_primary_history(Client(), "X/USD", date(2026,11,17))
        self.assertEqual(len(result), 3)
        self.assertEqual(result[-1][0], "2026-11-17T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
