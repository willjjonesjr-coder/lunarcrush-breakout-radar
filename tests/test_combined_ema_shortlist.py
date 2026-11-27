import unittest
from datetime import date

from tools.build_combined_ema_shortlist import build

CLOSED = date(2026, 11, 25)
EMAS = dict(ema50="2", ema100="1.5", ema200="1")


def prod(cid, score, **values):
    return dict({"id": str(cid), "symbol": f"ABC{cid}", "name": f"Asset {cid}",
                 "breakout_score": score, "history_selection": "ANALYZED",
                 "ranking_eligible": "True", "expected_complete_day": "2026-11-25T00:00:00+00:00",
                 "latest_price_day": "2026-11-25T00:00:00+00:00",
                 "market_cap_label": "MICRO CAP", "liquidity_label": "THIN"}, **values)


def provisional(cid, **values):
    return dict({"coin_id": str(cid), "symbol": f"ABC{cid}", "name": f"Asset {cid}",
                 "breakout_score": "999", "current_selection_status": "CURRENT_ANALYZED",
                 "refresh_status": "REFRESHED_PROVISIONAL", "history_last_day": "2026-11-25",
                 "history_bars": "300", "refreshed_technical_status": "PROVISIONAL EMA ALIGNED",
                 "exchange": "kraken", "pair": f"ABC{cid}/USD",
                 "price_corroboration_status": "UNKNOWN", **EMAS}, **values)


def inventory(*assets, as_of="2026-11-26"):
    return {"assets": assets, "as_of": as_of}


def verified(cid, state="EMA CONFIRMED"):
    return dict(coin_id=str(cid), selected_in_300=True, fresh_300_bar_history=True,
                last_completed_candle="2026-11-25", technical_status=state,
                exchange="coinbase", pair=f"ABC{cid}/USD")


class TestCombinedShortlist(unittest.TestCase):
    def test_same_ranking_with_current_scores_and_low_cap_labels(self):
        top, audit, summary = build(
            [prod(1, "81", **EMAS, ema_history_source="VERIFIED EXCHANGE MAPPING",
                  technical_status="EMA CONFIRMED"), prod(2, "89"), prod(3, "70")],
            inventory(verified(1)), [provisional(1), provisional(2), provisional(3)], CLOSED)
        self.assertEqual([(x["coin_id"], x["identity_status"]) for x in top],
                         [("2", "PROVISIONAL"), ("1", "VERIFIED"), ("3", "PROVISIONAL")])
        self.assertEqual(top[0]["breakout_score"], 89)
        self.assertEqual(top[0]["liquidity_label"], "THIN")
        self.assertEqual(top[0]["due_diligence_required"], "YES")
        self.assertEqual(summary["evaluable_by_identity"], {"PROVISIONAL": 2, "VERIFIED": 1})
        self.assertEqual(len(audit), 3)

    def test_same_ticker_wrong_name_known_conflicts_stale_and_short_history(self):
        candidates = [provisional(1, name="Other ABC1"),
                      provisional(2, price_corroboration_status="PRICE_CONFLICT_REVIEW"),
                      provisional(3, history_last_day="2026-11-22"),
                      provisional(4, history_bars="299"),
                      provisional(5, refreshed_technical_status="PROVISIONAL EMA NOT ALIGNED"),
                      provisional(6, refresh_status="REVIEW_CURRENT_SELECTION_CHANGE"),
                      provisional(7, ema200="nan"), provisional(99)]
        production = [prod(i, "70") for i in range(1, 8)]
        top, audit, summary = build(production, inventory(), candidates, CLOSED)
        self.assertEqual([x["coin_id"] for x in top], ["3", "4", "5", "6", "7"])
        self.assertEqual(top[2]["ema_status"], "EMA DOES NOT QUALIFY")
        self.assertTrue(all(x["ema_status"] == "EMA NOT EVALUATED"
                            for x in (top[0], top[1], top[3], top[4])))
        self.assertEqual([x["screen_status"] for x in audit],
                         ["CONFLICT_REVIEW", "CONFLICT_REVIEW", "STALE_PROVISIONAL",
                          "INCOMPLETE_PROVISIONAL", "NOT_ALIGNED", "PROVISIONAL_NOT_REFRESHED",
                          "INCOMPLETE_PROVISIONAL"])
        self.assertEqual(summary["provisional_rows_outside_snapshot"], 1)

    def test_verified_not_aligned_cannot_be_replaced_by_provisional(self):
        top, audit, _ = build([prod(1, "81", **EMAS, ema_history_source="VERIFIED EXCHANGE MAPPING",
                                         technical_status="EMA NOT CONFIRMED")],
                              inventory(verified(1, "EMA NOT CONFIRMED")), [provisional(1)], CLOSED)
        self.assertEqual(len(top), 1)
        self.assertEqual(audit[0]["identity_status"], "VERIFIED")
        self.assertEqual(top[0]["ema_status"], "EMA DOES NOT QUALIFY")

    def test_ema_neither_controls_eligibility_nor_changes_rank(self):
        top, audit, summary = build(
            [prod(1, "92"), prod(2, "70"), prod(3, "54.99"), prod(4, "55"),
             prod(5, "nan")],
            inventory(), [provisional(2), provisional(3)], CLOSED)
        self.assertEqual([x["coin_id"] for x in top], ["1", "2", "4"])
        self.assertEqual(top[0]["ema_status"], "EMA NOT EVALUATED")
        self.assertEqual(top[0]["identity_status"], "UNVERIFIED")
        self.assertEqual(top[1]["ema_status"], "EMA SUPPORTS BREAKOUT")
        self.assertEqual(audit[2]["ema_status"], "EMA SUPPORTS BREAKOUT")
        self.assertEqual(audit[2]["shortlist_status"], "BELOW_BREAKOUT_SCORE_THRESHOLD")
        self.assertEqual(audit[4]["shortlist_status"], "NO_CURRENT_BREAKOUT_SCORE")
        self.assertEqual(summary["shortlist_by_ema_status"],
                         {"EMA NOT EVALUATED": 2, "EMA SUPPORTS BREAKOUT": 1})

    def test_duplicate_id_and_stale_snapshots_are_errors(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build([prod(1, "30"), prod(1, "50")], inventory(), [], CLOSED)
        with self.assertRaisesRegex(ValueError, "Production snapshot"):
            build([prod(1, "30", expected_complete_day="2026-11-24")], inventory(), [], CLOSED)
        with self.assertRaisesRegex(ValueError, "Verified inventory"):
            build([prod(1, "30")], inventory(as_of="2026-11-25"), [], CLOSED)

    def test_noncurrent_or_ineligible_production_row_not_ranked(self):
        top, audit, _ = build([prod(1, "70", ranking_eligible="False"),
                               prod(2, "95", latest_price_day="2026-11-24")],
                              inventory(), [provisional(1), provisional(2)], CLOSED)
        self.assertFalse(top)
        self.assertEqual([x["screen_status"] for x in audit],
                         ["OUTSIDE_ELIGIBLE_COHORT", "NO_CURRENT_BREAKOUT_SCORE"])


if __name__ == "__main__":
    unittest.main()
