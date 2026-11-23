"""Regression tests for isolated provisional research ranking."""
import unittest
from datetime import date, timedelta

from tools.provisional_ema_research_ranking import build


def record(cid="1"):
    return dict(coin_id=cid, symbol="ABC", name="Alpha", breakout_score="78.2",
                research_ready="YES", primary_blocker="RESEARCH_TO_PRODUCTION_HANDOFF",
                identity_status="UNIQUE EXACT CANDIDATE — NOT VERIFIED",
                price_corroboration_status="PRICE_CORROBORATED")


def prod(cid="1", expected="2026-11-21"):
    return dict(id=cid, symbol="ABC", name="Alpha", history_selection="ANALYZED",
                expected_complete_day=expected, technical_status="INSUFFICIENT EMA HISTORY",
                ema50="", ema100="", ema200="", breakout_score="78.2",
                liquidity_label="BELOW VOLUME REFERENCE")


def provisional(cid="1", day="2026-11-21"):
    return dict(coin_id=cid, symbol="ABC", name="Alpha",
                status="PROVISIONAL READY",
                provisional_technical_status="PROVISIONAL EMA ALIGNED",
                provisional_ema50="1.2", provisional_ema100="1.1",
                provisional_ema200="0.8", bars="500", latest_day=day)


class RankingTests(unittest.TestCase):
    def test_fresh_still_never_alerts_or_promotes(self):
        r, summary = build([record()], [prod()], provisional=[provisional()],
                           provisional_report={"as_of":"2026-11-22",
                                               "required_completed_day":"2026-11-21"})
        self.assertEqual(summary["fresh_ema"], 1)
        self.assertEqual(r[0]["alert_eligible"], "NO")
        self.assertEqual(r[0]["production_eligible"], "NO")
        self.assertIn("IDENTITY_PROVISIONAL_USER_REVIEW", r[0]["caution_flags"])

    def test_old_report_marked_stale_not_actionable(self):
        r, summary = build([record()], [prod()], provisional=[provisional()],
                           provisional_report={"as_of":"2026-11-20",
                                               "required_completed_day":"2026-11-19"})
        self.assertEqual(summary["stale_or_unverified_ema"], 1)
        self.assertEqual(r[0]["research_priority"], "REFRESH_OR_RECONCILE_EVIDENCE")

    def test_price_without_dates_cannot_claim_fresh(self):
        r, _ = build([record()], [prod()], price=[dict(
            coin_id="1", symbol="ABC", name="Alpha",
            ema_status="PROVISIONAL EMA ALIGNED", ema50="1", ema100="0.9",
            ema200="0.8")])
        self.assertEqual(r[0]["evidence_freshness"], "STALE_OR_UNVERIFIED")
        self.assertIn("PRICE_EMA_DATE_NOT_VERIFIED", r[0]["caution_flags"])

    def test_conflicting_source_fail_closed(self):
        r, _ = build([record()], [prod()], provisional=[dict(
            provisional(), symbol="XYZ")])
        self.assertEqual(r[0]["evidence_freshness"], "MISSING_VALUES")
        self.assertIn("PROVISIONAL_IDENTITY_CONFLICT", r[0]["caution_flags"])

    def test_duplicate_source_rejected(self):
        source = provisional()
        r, _ = build([record()], [prod()], provisional=[source, source])
        self.assertIn("DUPLICATE_SOURCE_ID", r[0]["caution_flags"])
        self.assertEqual(r[0]["evidence_freshness"], "MISSING_VALUES")

    def test_rank_by_score_not_liquidity(self):
        first = record("1")
        second = dict(record("2"), breakout_score="90")
        r, _ = build([first,second], [prod("1"),prod("2")])
        self.assertEqual([x["coin_id"] for x in r], ["2","1"])

    def test_duplicate_coverage_fails(self):
        with self.assertRaises(ValueError):
            build([record(),record()], [prod()])

    def test_existing_production_ema_fails(self):
        with self.assertRaises(ValueError):
            build([record()], [dict(prod(), ema50="1")])

    def test_unanalyzed_production_fails(self):
        with self.assertRaises(ValueError):
            build([record()], [dict(prod(), history_selection="NOT ANALYZED")])


if __name__ == "__main__":
    unittest.main()
