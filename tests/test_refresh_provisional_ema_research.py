"""Offline safety tests for current provisional EMA refresh."""
import unittest
from datetime import date
from unittest.mock import patch

from tools.refresh_provisional_ema_research import refresh, eligible_pair


def ranking(cid="1", status="CURRENT_ANALYZED"):
    return {"coin_id": cid, "name": "Alpha", "symbol": "ABC",
            "research_rank": "1", "breakout_score": "55",
            "current_selection_status": status,
            "provisional_ema_status": "PROVISIONAL EMA NOT ALIGNED",
            "ema_evidence_day": "2026-11-03"}


def source(cid="1", **other):
    result = {"coin_id": cid, "name": "Alpha", "symbol": "ABC",
              "status": "PROVISIONAL READY", "exchange": "kraken",
              "pair": "ABC/USD"}
    result.update(other)
    return result


def prod(cid="1", selection="ANALYZED"):
    return {"id": cid, "name": "Alpha", "symbol": "ABC",
            "history_selection": selection}


class Client:
    def load_markets(self):
        pass


class RefreshTests(unittest.TestCase):
    def test_refresh_exact_pair_and_keep_alerts_off(self):
        candles = [["2026-11-22T00:00:00Z",1,2,.5,1,99]] * 300
        with patch("tools.refresh_provisional_ema_research.fetch_history", return_value=candles) as fetch, \
             patch("tools.refresh_provisional_ema_research.provisional_technicals",
                   return_value={"provisional_technical_status":"PROVISIONAL EMA ALIGNED",
                                 "provisional_ema50":1.1,"provisional_ema100":1.,
                                 "provisional_ema200":.9}):
            out, summary = refresh([ranking()], {"assets":[source()]},
                                   [prod()], lambda v: Client(),
                                   today=date(2026,11,23))
        self.assertEqual(summary["refreshed"],1)
        self.assertEqual(summary["refreshed_aligned"],1)
        self.assertEqual(out[0]["alert_eligible"], "NO")
        self.assertEqual(out[0]["production_eligible"], "NO")
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[1],"ABC/USD")

    def test_historical_outside_current_selection_retained_without_fetch(self):
        with patch("tools.refresh_provisional_ema_research.fetch_history") as fetch:
            out, summary = refresh([ranking()], {"assets":[source()]},
                                   [prod("2")], lambda _: Client(),
                                   today=date(2026,11,23))
        fetch.assert_not_called()
        self.assertEqual(summary["historical_retained"],1)
        self.assertEqual(out[0]["refresh_status"],"RETAINED_HISTORICAL_ONLY")

    def test_ambiguous_pair_rejected(self):
        decision,_,_ = eligible_pair(source(pair="ABC/USDT:USDT"), ranking())
        self.assertEqual(decision,"UNSUPPORTED_OR_CONFLICTING_PAIR")

    def test_wrong_name_rejected_without_fetch(self):
        changed = dict(source(), name="Another Alpha")
        with patch("tools.refresh_provisional_ema_research.fetch_history") as fetch:
            out,_ = refresh([ranking()], {"assets":[changed]},
                            [prod()], lambda _: Client(),
                            today=date(2026,11,23))
        self.assertEqual(out[0]["refresh_status"],"IDENTITY_CONFLICT")
        fetch.assert_not_called()

    def test_old_selection_change_requires_review(self):
        with patch("tools.refresh_provisional_ema_research.fetch_history") as fetch:
            out,_ = refresh([ranking(status="NOT_IN_CURRENT_REPORT")],
                            {"assets":[source()]},[prod()],
                            lambda _: Client(),today=date(2026,11,23))
        self.assertEqual(out[0]["refresh_status"],"REVIEW_CURRENT_SELECTION_CHANGE")
        fetch.assert_not_called()

    def test_history_failure_does_not_abort_batch(self):
        def broken(*args):
            raise ValueError("Missing latest candle")
        with patch("tools.refresh_provisional_ema_research.fetch_history", side_effect=broken):
            out, summary = refresh([ranking()],{"assets":[source()]},
                                   [prod()], lambda _: Client(),today=date(2026,11,23))
        self.assertEqual(summary["refreshed"],0)
        self.assertEqual(out[0]["refresh_status"],"REFRESH_FAILED")
        self.assertFalse(out[0]["ema50"])

    def test_duplicate_asset_ids_fail_closed(self):
        with self.assertRaises(ValueError):
            refresh([ranking(),ranking()],{"assets":[source()]},[prod()],
                    lambda _: Client(),today=date(2026,11,23))


if __name__ == "__main__":
    unittest.main()
