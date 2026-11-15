import tempfile
import unittest
from pathlib import Path
from tools.build_incremental_cex_identity_readiness import report, write


def r(cid, exchange, status="NO_EXACT_SPOT_PAIR", market="NO_EXACT_SPOT_PAIR", bars="0"):
    return {"coin_id": cid, "exchange":exchange, "history_status":status,
            "market_status":market, "bars_available":bars, "pair":"ABC/USDT",
            "latest_day":"2026-11-14", "breakout_score":"64"}

class IdentityReadinessTests(unittest.TestCase):
    def test_incremental_coins_only_and_no_auto_approvals(self):
        before = [
            {"coin_id":"1","symbol":"ABC","name":"Alpha","incremental_300_bar_discovery":"True"},
            {"coin_id":"2","symbol":"DEF","name":"Delta","incremental_300_bar_discovery":"False"}]
        coverage = [
            r("1","kraken"),
            r("1","mexc","500_BAR_READY_PROVISIONAL","FOUND_PROVISIONAL","500"),
            r("2","gate","500_BAR_READY_PROVISIONAL","FOUND_PROVISIONAL","500")]
        result = report(before, coverage)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["source_markets"],"mexc:ABC/USDT")
        self.assertEqual(result[0]["production_approval"],"NO")
        self.assertEqual(result[0]["identity_state"],"UNVERIFIED")
        self.assertEqual(result[0]["cross_venue_price_check"],"NOT_DONE")

    def test_missing_underlying_history_fails_closed(self):
        before = [{"coin_id":"3","symbol":"XYZ","incremental_300_bar_discovery":"True"}]
        with self.assertRaises(ValueError):
            report(before,[r("3","mexc","SHORT_HISTORY","FOUND_PROVISIONAL","40")])

if __name__=="__main__":
    unittest.main()
