"""Regression tests for read-only coverage classification."""
import unittest

from tools.unified_ema_coverage_audit import make


def prod(cid, **kwargs):
    row = {"id": str(cid), "symbol": "ABC", "name": "Alpha",
           "history_selection": "ANALYZED", "breakout_score": "80",
           "technical_status": "INSUFFICIENT EMA HISTORY", "ema50": "",
           "ema100": "", "ema200": ""}
    row.update(kwargs)
    return row


class CoverageTest(unittest.TestCase):
    def test_no_artifacts_are_unknown_not_identity_failures(self):
        result, summary = make([prod(1)])
        self.assertEqual(summary["production_ema_missing"], 1)
        self.assertEqual(result[0]["primary_blocker"], "NO_MATCHING_RESEARCH_ARTIFACT")
        self.assertEqual(result[0]["identity_status"], "UNKNOWN")
        self.assertEqual(result[0]["research_ready"], "NO")

    def test_research_ready_never_promotes_production(self):
        result, summary = make(
            [prod(1)],
            price=[{"coin_id": "1", "symbol": "ABC",
                    "corroboration_status": "PRICE_CORROBORATED"}],
            provisional=[{"coin_id": "1", "symbol": "ABC",
                          "provisional_technical_status": "PROVISIONAL EMA ALIGNED",
                          "history_bars": "500"}])
        self.assertEqual(result[0]["primary_blocker"], "RESEARCH_TO_PRODUCTION_HANDOFF")
        self.assertEqual(result[0]["research_ready"], "YES")
        self.assertEqual(result[0]["production_ema_evaluable"], "NO")
        self.assertEqual(summary["provisional_research_ready"], 1)

    def test_conflicting_identity_blocks_research(self):
        result, _ = make([prod(1)], identity=[{"coin_id": "1", "final_decision": "AMBIGUOUS"}],
                         provisional=[{"coin_id": "1", "status": "PROVISIONAL READY",
                                       "provisional_technical_status": "PROVISIONAL EMA ALIGNED"}])
        self.assertEqual(result[0]["primary_blocker"], "IDENTITY_OR_PRICE_CONFLICT")
        self.assertEqual(result[0]["research_ready"], "NO")

    def test_mismatched_symbols_do_not_join(self):
        result, _ = make([prod(1)], price=[{"coin_id": "1", "symbol": "XYZ",
                                            "corroboration_status": "PRICE_CORROBORATED"}])
        self.assertEqual(result[0]["primary_blocker"], "EVIDENCE_CONFLICT")
        self.assertNotIn("price", result[0]["artifact_sources"])

    def test_duplicate_artifact_ids_fail_closed(self):
        result, _ = make([prod(1)], price=[{"coin_id": "1"}, {"coin_id": "1"}])
        self.assertEqual(result[0]["primary_blocker"], "EVIDENCE_CONFLICT")

    def test_production_ema_not_overwritten(self):
        result, summary = make([prod(1, ema50="1", ema100="2", ema200="3")])
        self.assertEqual(result[0]["primary_blocker"], "PRODUCTION_EMA_AVAILABLE")
        self.assertEqual(summary["production_ema_evaluable"], 1)

    def test_selection_excludes_outside_budget(self):
        result, summary = make([prod(1), prod(2, history_selection="NOT ANALYZED")])
        self.assertEqual(len(result), 1)
        self.assertEqual(summary["production_candidates"], 1)

    def test_no_duplicate_production_ids(self):
        with self.assertRaises(ValueError):
            make([prod(1), prod(1)])


if __name__ == "__main__":
    unittest.main()
