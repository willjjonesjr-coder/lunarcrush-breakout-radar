"""Offline regression coverage for the next 212 missing-EMA research candidates."""
import unittest
from tools.build_ema_coverage_expansion_queue import build

def prod(cid, score="50", **kw):
    return dict({"id":cid,"name":"Token "+cid,"symbol":"T"+cid,
                 "history_selection":"ANALYZED","breakout_score":score,
                 "market_cap":"1000","liquidity_label":"BELOW VOLUME REFERENCE",
                 "ema50":"","ema100":"","ema200":""},**kw)

def cov(cid, blocker="UNCLASSIFIED_MISSING_EMA", score="50"):
    return {"coin_id":cid,"name":"Token "+cid,"symbol":"T"+cid,
            "primary_blocker":blocker,"breakout_score":score}

class CoverageExpansionTests(unittest.TestCase):
    def test_exact_212_cohort_is_partitioned_by_blocker(self):
        coverage = [cov(str(i),"NO_MATCHING_RESEARCH_ARTIFACT" if i<=112
                        else "UNCLASSIFIED_MISSING_EMA",str(i)) for i in range(1,213)]
        production = [prod(str(i),str(i)) for i in range(1,213)]
        all_rows,batch,summary=build(coverage,production,40)
        self.assertEqual(len(all_rows),212)
        self.assertEqual(len(batch),40)
        self.assertEqual(summary["eligible_blockers"]["NO_MATCHING_RESEARCH_ARTIFACT"],112)
        self.assertEqual(summary["eligible_blockers"]["UNCLASSIFIED_MISSING_EMA"],100)
        self.assertEqual(batch[0]["coin_id"],"212")
        self.assertEqual(batch[0]["research_only"],"YES")

    def test_low_cap_retained(self):
        all_rows,_,_=build([cov("1")],[prod("1")])
        self.assertEqual(all_rows[0]["market_cap"],"1000")

    def test_conflicts_and_existing_ema_withheld(self):
        all_rows,_,summary=build([cov("1"),cov("2")],[prod("1",name="Another"),prod("2",ema50="0.1")])
        self.assertEqual(all_rows,[])
        self.assertEqual(summary["skipped"]["NAME_SYMBOL_CONFLICT"],1)
        self.assertEqual(summary["skipped"]["PRODUCTION_EMA_ALREADY_PRESENT"],1)

    def test_never_rescan_provisional_ready_or_verified(self):
        all_rows,_,_=build([cov("1","RESEARCH_TO_PRODUCTION_HANDOFF"),
                             cov("2","PRODUCTION_EMA_AVAILABLE")],[prod("1"),prod("2")])
        self.assertEqual(all_rows,[])

    def test_duplicate_coin_id_fails_closed(self):
        with self.assertRaises(ValueError):
            build([cov("1"),cov("1")],[prod("1")])

    def test_duplicate_production_withheld(self):
        rows,_,summary=build([cov("1")],[prod("1"),prod("1")])
        self.assertFalse(rows)
        self.assertEqual(summary["skipped"]["SOURCE_PRODUCTION_MISSING_OR_DUPLICATED"],1)

    def test_batch_bounds(self):
        with self.assertRaises(ValueError):
            build([cov("1")],[prod("1")],0)

if __name__=="__main__":
    unittest.main()
