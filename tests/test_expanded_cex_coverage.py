"""Offline regression tests for the research-only expanded CEX coverage audit."""
import unittest
from datetime import date, datetime, timezone
from tools.audit_expanded_cex_coverage import markets_for_coin, validate_bars, audit, summarize


def candles(n=300, start=date(2025, 1, 1)):
    from datetime import timedelta
    return [[int(datetime.combine(start + timedelta(days=i), datetime.min.time(), timezone.utc).timestamp()*1000),
             1, 2, 0.5, 1.5, 100] for i in range(n)]


class FakeExchange:
    def __init__(self, markets=None):
        self.markets = markets or {}
        self.has = {"fetchOHLCV": True}
        self.calls = 0
    def fetch_ohlcv(self, *args, **kwargs):
        self.calls += 1
        return candles(300, date(2026, 1, 1))


class ExpandedCexAuditTests(unittest.TestCase):
    def test_market_filter_rejects_derivatives_and_wrong_base(self):
        ex = FakeExchange({
            "abc": {"symbol":"ABC/USDT", "id":"ABCUSDT", "base":"ABC", "quote":"USDT", "spot":True, "active":True},
            "swap": {"symbol":"ABC/USDT:USDT", "base":"ABC", "quote":"USDT", "spot":False, "active":True},
            "wrong": {"symbol":"ABC/USD", "base":"XYZ", "quote":"USD", "spot":True, "active":True},
            "inactive": {"symbol":"ABC/USDC", "base":"ABC", "quote":"USDC", "spot":True, "active":False},
        })
        self.assertEqual([x["symbol"] for x in markets_for_coin(ex, "ABC")], ["ABC/USDT"])

    def test_complete_history_is_always_provisional(self):
        result = validate_bars(candles(), date(2026, 10, 27))
        self.assertEqual(result["status"], "300_BAR_READY_PROVISIONAL")
        result = validate_bars(candles(), date(2026, 10, 27), preferred=500)
        self.assertEqual(result["status"], "300_BAR_READY_PROVISIONAL")

    def test_completed_and_short_history(self):
        from datetime import timedelta
        start = date(2026, 1, 1)
        end = start + timedelta(days=299)
        self.assertEqual(validate_bars(candles(), end)["status"], "300_BAR_READY_PROVISIONAL")
        self.assertEqual(validate_bars(candles(50), start + timedelta(days=49))["status"], "SHORT_HISTORY")

    def test_missing_gap_breaks_suffix(self):
        bars = candles()
        bars.pop(250)
        result = validate_bars(bars, date(2026, 10, 27))
        self.assertEqual(result["status"], "SHORT_HISTORY")
        self.assertEqual(result["bars"], 49)

    def test_unknown_market_remains_unapproved(self):
        coin = {"review_rank":1, "coin_id":"99", "name":"Alpha", "symbol":"ABC", "breakout_score":70}
        ex = FakeExchange({"abc":{"symbol":"ABC/USDT","id":"ABCUSDT","base":"ABC","quote":"USDT","spot":True,"active":True}})
        rows = audit([coin], {"mexc":ex, "gate":FakeExchange()}, date(2026, 10, 27))
        found = [r for r in rows if r["market_status"] == "FOUND_PROVISIONAL"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["identity_status"], "UNVERIFIED_SYMBOL_MATCH_ONLY")
        self.assertEqual(found[0]["approval_status"], "RESEARCH_ONLY_DO_NOT_IMPORT")
        self.assertEqual(summarize(rows, 1)["approved"], 0)


if __name__ == "__main__":
    unittest.main()
