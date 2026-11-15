import unittest
from tools.compare_cex_coverage import compare, summary


def row(cid, exchange, market="NO_EXACT_SPOT_PAIR", history="NOT_CHECKED", pair=""):
    return {"coin_id":cid, "symbol":"X", "name":"Example",
            "exchange":exchange, "market_status":market,
            "history_status":history, "pair":pair}


class ComparisonTests(unittest.TestCase):
    def test_additional_market_and_history_are_incremental(self):
        rows=[row("10","kraken"),
              row("10","mexc","FOUND_PROVISIONAL","300_BAR_READY_PROVISIONAL","X/USDT")]
        found=compare(rows)
        self.assertTrue(found[0]["incremental_market_discovery"])
        self.assertTrue(found[0]["incremental_300_bar_discovery"])
        self.assertEqual(summary(found,rows)["incremental_300_bar_discovery"],1)
        self.assertEqual(summary(found,rows)["identity_approvals"],0)

    def test_existing_three_already_covered(self):
        rows=[row("20","coinbase","FOUND_PROVISIONAL","500_BAR_READY_PROVISIONAL","X/USD"),
              row("20","gate","FOUND_PROVISIONAL","500_BAR_READY_PROVISIONAL","X/USDT")]
        x=compare(rows)[0]
        self.assertFalse(x["incremental_market_discovery"])
        self.assertFalse(x["incremental_300_bar_discovery"])

    def test_short_history_not_mature_ready(self):
        rows=[row("30","binance"),row("30","bitget","FOUND_PROVISIONAL","SHORT_HISTORY","X/USDT")]
        x=compare(rows)[0]
        self.assertTrue(x["incremental_market_discovery"])
        self.assertFalse(x["incremental_300_bar_discovery"])

    def test_unavailable_baseline_flagged(self):
        rows=[row("40","kraken","EXCHANGE_UNAVAILABLE"),
              row("40","okx","FOUND_PROVISIONAL","300_BAR_READY_PROVISIONAL","X/USDT")]
        x=compare(rows)[0]
        self.assertEqual(x["recommendation"],"ORIGINAL_EXCHANGE_UNAVAILABLE_REVIEW")
        self.assertEqual(x["original_exchanges_unavailable"],"kraken")
        self.assertIn("kraken",summary(compare(rows),rows)["exchange_checks_unavailable"])

    def test_many_rows_do_not_double_count_coin(self):
        rows=[row("50","mexc","FOUND_PROVISIONAL","SHORT_HISTORY","X/USDT"),
              row("50","mexc","FOUND_PROVISIONAL","500_BAR_READY_PROVISIONAL","X/USDC")]
        x=compare(rows)
        self.assertEqual(len(x),1)
        self.assertEqual(summary(x,rows)["additional_market_found"],1)


if __name__ == "__main__":
    unittest.main()
