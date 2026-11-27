import csv
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from tests.test_combined_ema_shortlist import CLOSED, inventory, prod, provisional
from tools.alternate_ema_research import GateSpot, KrakenSpot, audit
from tools.build_combined_ema_shortlist import build


def ticker(venue, base="ABC1", cg="test-asset", **fields):
    return dict(dict(market={"identifier": venue}, base=base, target="USDT", coin_id=cg,
                     is_stale=False, is_anomaly=False), **fields)


class Client:
    def __init__(self, venue, markets=True):
        self.venue = venue
        self.markets = {"unrelated": dict(base="OTHER", quote="USD", spot=True, active=True)} if markets else {}

    def load_markets(self):
        return self.markets


class AlternateResearchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        with (self.path / "history_1.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["coin_id", "time", "close"])
            w.writerows([["1", (CLOSED - timedelta(days=i)).isoformat() + "T00:00:00Z", 2]
                         for i in (2, 1, 0)])
        self.production = [prod(1, "74"), prod(2, "70"), prod(3, "54"), prod(4, "60")]
        self.original = [provisional(2, refresh_status="IDENTITY_CONFLICT"), provisional(4)]
        self.short, self.all_rows, self.summary = build(self.production, inventory(), self.original, CLOSED)

    @staticmethod
    def prices(client, pair, end, count):
        price = 2.03 if client.venue == "gate" else 2.07
        return [[(end - timedelta(days=i)).isoformat() + "T00:00:00Z", price, price, price, price, 1]
                for i in reversed(range(count))]

    def run_audit(self, tickers, factory=Client):
        def get(path):
            if path.startswith("/coins/list"):
                return [dict(id="test-asset", symbol="abc1", name="Asset 1")]
            self.assertEqual(path, "/coins/test-asset/tickers")
            return {"tickers": tickers}
        return audit(self.short, self.production, CLOSED, self.path, {}, get, factory, self.prices)

    def test_gate_without_kraken_preserves_ranks_and_holds(self):
        result = self.run_audit([ticker("gate"), ticker("okex")])
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual((row["status"], row["exchange"], row["kraken_usd_spot"], row["corroborating_venues"]),
                         ("CORROBORATED", "gate", "NO_ACTIVE_EXACT_PAIR", 1))
        self.assertEqual([a["status"] for a in row["attempts"]], ["PRICE_DISAGREEMENT", "CORROBORATED"])
        self.assertEqual(len(row["attempts"][1]["comparison"]), 3)
        top, all_rows, summary = build(self.production, inventory(), self.original, CLOSED, result)
        self.assertEqual([r["coin_id"] for r in top], ["1", "4"])
        self.assertEqual([r["research_rank"] for r in top], [1, 2])
        self.assertEqual(top[0]["identity_status"], "PROVISIONAL")
        self.assertEqual(top[0]["alternate_price_disagreement"], "YES")
        self.assertEqual(top[0]["ema_status"], "EMA DOES NOT QUALIFY")
        self.assertEqual(all_rows[1]["shortlist_status"], "CONFLICT_REVIEW")
        self.assertEqual(top[1]["exchange"], "kraken")
        self.assertEqual(summary["shortlist_count"], self.summary["shortlist_count"])

    def test_listing_conflict_staleness_and_api_failure_do_not_grant_badge(self):
        self.assertEqual(self.run_audit([ticker("gate", cg="different")])[0]["status"],
                         "IDENTITY_OR_LISTING_REVIEW")
        self.assertEqual(self.run_audit([ticker("gate", is_stale=True)])[0]["attempts"], [])
        r = self.run_audit([ticker("gate")], lambda v: Client(v, markets=(v != "kraken")))[0]
        self.assertEqual(r["kraken_usd_spot"], "UNKNOWN")
        r["closed_day"] = (CLOSED - timedelta(days=1)).isoformat()
        top, _, _ = build(self.production, inventory(), self.original, CLOSED, [r])
        self.assertEqual(top[0]["ema_status"], "EMA NOT EVALUATED")

    def test_score_still_qualifies_when_no_exchange_passes(self):
        result = self.run_audit([ticker("okex")])
        self.assertEqual(result[0]["status"], "NO_USABLE_ALTERNATE")
        top, _, _ = build(self.production, inventory(), self.original, CLOSED, result)
        self.assertEqual(top[0]["research_rank"], 1)
        self.assertEqual(top[0]["ema_status"], "EMA NOT EVALUATED")

    def test_coin_gecko_down_leaves_score_shortlist(self):
        def fail(_):
            raise RuntimeError("API unavailable")
        result = audit(self.short, self.production, CLOSED, self.path, {}, fail, Client)
        self.assertEqual(result[0]["status"], "COINGECKO_CATALOG_UNAVAILABLE")
        top, _, _ = build(self.production, inventory(), self.original, CLOSED, result)
        self.assertEqual(top[0]["alternate_venue_status"], "COINGECKO_CATALOG_UNAVAILABLE")
        self.assertEqual(top[0]["research_rank"], 1)


    def test_spot_catalogs_and_gate_candle_mapping(self):
        market = [{"base": "ABC1", "quote": "USDT", "id": "ABC1_USDT", "trade_status": "tradable"}]
        data = [["86400", "42", "2", "3", "1", "1.5", "20", "true"],
                ["172800", "42", "2", "3", "1", "1.5", "20", "false"]]
        with patch("tools.alternate_ema_research.public_json", side_effect=[market, data]) as fetch:
            c = GateSpot()
            c.load_markets()
            self.assertTrue(c.markets["ABC1/USDT"]["active"])
            self.assertEqual(c.fetch_ohlcv("ABC1/USDT", "1d", 86400000, 2),
                             [[86400000, 1.5, 3., 1., 2., 20.]])
            self.assertIn("currency_pair=ABC1_USDT", fetch.call_args.args[0])
        with patch("tools.alternate_ema_research.public_json", return_value={
                "error": [], "result": {"abc": {"wsname": "ABC1/USD", "status": "cancel_only"}}}):
            k = KrakenSpot()
            k.load_markets()
            self.assertFalse(k.markets["ABC1/USD"]["active"])
