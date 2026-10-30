import csv
import json
import tempfile
import unittest
from pathlib import Path

from undervaluation_radar import evaluate, run


def eligible(i, sector="DeFi"):
    return {
        "id": i, "symbol": "COIN" + str(i), "breakout_score": 60 + i,
        "fundamentals_mapping": "exact_name_and_symbol",
        "fundamentals_confidence": "MODERATE",
        "fundamentals_sector": sector,
        "fundamentals_holder_revenue_365d": 100,
        "fundamentals_market_cap_to_holder_revenue_365d": 8 + i,
        "fundamentals_fees_growth_30d": .2,
        "fundamentals_revenue_growth_30d": .1,
        "fundamentals_holder_revenue_growth_30d": .1,
        "fundamentals_fdv_to_market_cap": 1.2,
        "price_change_30d": -.35, "price_change_7d": -.10,
        "volume_24h_snapshot": 10_000_000, "volume_daily_accel": .3,
        "technical_status": "EMA NOT CONFIRMED",
    }


class UndervaluationTests(unittest.TestCase):
    def test_price_crash_alone_is_never_undervaluation(self):
        result = evaluate([{"id": 1, "price_change_30d": -.8, "price_change_7d": -.5}])[0]
        self.assertIsNone(result["undervaluation_score"])
        self.assertEqual(result["undervaluation_classification"], "UNRATED")
        self.assertIn("SELL-OFF", result["undervaluation_price_context"])

    def test_requires_three_peers_and_holder_economics(self):
        results = evaluate([eligible(1), eligible(2)])
        self.assertTrue(all(r["undervaluation_score"] is None for r in results))
        full = evaluate([eligible(1), eligible(2), eligible(3)])
        self.assertTrue(all(r["undervaluation_score"] is not None for r in full))
        self.assertEqual([r["breakout_score"] for r in full], [61, 62, 63])
        self.assertGreater(full[0]["undervaluation_score"], full[2]["undervaluation_score"])

    def test_missing_data_never_fabricates_zero(self):
        rows = [eligible(1), eligible(2), eligible(3)]
        del rows[0]["fundamentals_holder_revenue_365d"]
        result = evaluate(rows)
        self.assertTrue(all(r["undervaluation_score"] is None for r in result))

    def test_report_outputs_preserve_breakout_and_csv_parity(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)
            rows = [eligible(i) for i in (1, 2, 3)]
            (p / "breakout_radar.json").write_text(json.dumps(rows))
            with (p / "breakout_radar.csv").open("w", newline="") as h:
                writer = csv.DictWriter(h, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            run(p)
            enriched = json.loads((p / "breakout_radar.json").read_text())
            data = json.loads((p / "undervaluation_radar.json").read_text())
            with (p / "breakout_radar.csv").open(newline="") as h:
                csvrows = list(csv.DictReader(h))
            self.assertEqual(data["rated"], 3)
            self.assertEqual([x["breakout_score"] for x in enriched], [61, 62, 63])
            self.assertEqual([float(r["undervaluation_score"]) for r in csvrows],
                             [r["undervaluation_score"] for r in enriched])


if __name__ == "__main__":
    unittest.main()
