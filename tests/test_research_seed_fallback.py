"""Pinned identity evidence and no-network research shortlist regression tests."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from tests.test_combined_ema_shortlist import CLOSED, inventory, prod
from tools.build_combined_ema_shortlist import build
from tools.refresh_provisional_ema_research import load_seed, refresh, retain_baseline_holds


class SeedFallbackTests(unittest.TestCase):
    def test_seed_verifies_and_modified_file_fails_closed(self):
        ranking, original, source = load_seed()
        self.assertEqual(len(ranking), 41)
        self.assertEqual(len(original["assets"]), 40)
        self.assertEqual(source["identity"]["artifact_id"], 13292082440)
        self.assertEqual(source["ranking"]["artifact_id"], 14869400733)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrupt.json"
            path.write_text('{"schema_version":1,"ranking":[]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not safe to publish"):
                load_seed(path)

    def test_no_history_still_has_fresh_scores_verified_ema_and_holds(self):
        ranking, original, _ = load_seed()
        hold_rows = [prod(152191, "65", symbol="ZBCN", name="Zebec Network"),
                     prod(74232, "66", symbol="MPLX", name="Metaplex")]
        verified = prod(1, "71", ema50="2", ema100="1.5", ema200="1",
                        ema_history_source="VERIFIED EXCHANGE MAPPING",
                        technical_status="EMA NOT CONFIRMED")
        current = [verified, prod(2, "70"), *hold_rows]
        info = inventory(dict(coin_id="1", selected_in_300=True, fresh_300_bar_history=True,
                              last_completed_candle=CLOSED.isoformat(), exchange="kraken",
                              pair="ABC1/USD", technical_status="EMA NOT CONFIRMED"))
        with patch("tools.refresh_provisional_ema_research.fetch_history") as market:
            rows, summary = refresh(ranking, original, current, None,
                                    today=CLOSED+timedelta(days=1), plan_only=True)
            market.assert_not_called()
        top, audit, output = build(current, info, rows, CLOSED)
        self.assertEqual(summary["required_completed_day"], CLOSED.isoformat())
        self.assertEqual(summary["refreshed"], 0)
        self.assertEqual([r["coin_id"] for r in top], ["1", "2"])
        self.assertEqual(top[0]["identity_status"], "VERIFIED")
        self.assertEqual(top[1]["ema_status"], "EMA NOT EVALUATED")
        self.assertEqual(output["screen_counts"]["CONFLICT_REVIEW"], 2)
        self.assertEqual({r["coin_id"] for r in audit if r["screen_status"] == "CONFLICT_REVIEW"},
                         {"152191", "74232"})
        with self.assertRaisesRegex(ValueError, "does not match requested"):
            build(current, info, rows, date(2026, 11, 26))

    def test_optional_archive_cannot_clear_or_drop_retained_holds(self):
        a = dict(coin_id="152191", refresh_status="PRICE_CONFLICT_REVIEW")
        b = dict(coin_id="74232", current_selection_status="CURRENT_IDENTITY_CONFLICT")
        update = dict(coin_id="152191", refresh_status="REFRESHED_PROVISIONAL")
        self.assertEqual(retain_baseline_holds([update], [a, b]), [a, b])
        self.assertEqual(retain_baseline_holds([update], []), [update])
