"""Audit must preserve independent source values and fail closed on gaps."""
import unittest
from tools.build_ema_master_identity_audit import make, compare_contract

def stage():
    return [{"coin_id":"151373","symbol":"DRIFT","name":"Drift Protocol",
             "exchange":"kraken","pair":"DRIFT/USD","status":"STAGED"}]

def canonical(**changes):
    x={"coin_id":"151373","coingecko_id":"drift-protocol",
       "coingecko_name":"Drift Protocol","coingecko_symbol":"DRIFT",
       "identity_status":"UNIQUE EXACT CANDIDATE — NOT VERIFIED",
       "platform_contracts":'{"solana":"So1anaMintABC"}'}
    x.update(changes)
    return [x]

def evidence(**changes):
    x={"coin_id":"151373","coingecko_id":"drift-protocol",
       "coingecko_exchange_listing":"FOUND","coin_platforms":'{"solana":"So1anaMintABC"}'}
    x.update(changes)
    return [x]

class IdentityAuditTests(unittest.TestCase):
    def test_true_symbol_and_name_comparisons_are_recorded(self):
        row=make(stage(),canonical(),evidence(),{})[0]
        self.assertEqual(row["lunarcrush_coingecko_symbol_comparison"],"MATCH")
        self.assertEqual(row["lunarcrush_coingecko_name_comparison"],"MATCH")
        self.assertEqual(row["coingecko_id_cross_source_comparison"],"MATCH")
        self.assertEqual(row["final_decision"],"PENDING")
        self.assertEqual(row["exchange_canonical_comparison"],"UNKNOWN")

    def test_missing_canonical_symbol_is_unknown_not_self_match(self):
        row=make(stage(),canonical(coingecko_symbol=""),evidence(),{})[0]
        self.assertEqual(row["lunarcrush_coingecko_symbol_comparison"],"UNKNOWN")
        self.assertEqual(row["lunarcrush_canonical_comparison"],"UNKNOWN")
        self.assertIn("independent CoinGecko symbol not captured",row["evidence_gaps"])

    def test_disagreement_makes_identity_ambiguous(self):
        row=make(stage(),canonical(coingecko_name="Unrelated Project"),evidence(),{})[0]
        self.assertEqual(row["lunarcrush_coingecko_name_comparison"],"MISMATCH")
        self.assertEqual(row["final_decision"],"AMBIGUOUS")

    def test_conflicting_canonical_ids_are_exposed(self):
        row=make(stage(),canonical(),evidence(coingecko_id="different-asset"),{})[0]
        self.assertEqual(row["coingecko_id_cross_source_comparison"],"MISMATCH")
        self.assertEqual(row["final_decision"],"AMBIGUOUS")

    def test_contract_case_sensitive_on_solana(self):
        self.assertEqual(compare_contract("So1anaMintABC","so1anamintabc","solana"),"MISMATCH")
        self.assertEqual(compare_contract("0xABCD","0xabcd","ethereum"),"MATCH")

    def test_official_contract_comparison_not_exchange_approval(self):
        approvals={"151373":{"network":"solana","contract_address":"So1anaMintABC",
                  "status":"approved","exchange":"kraken","pair":"DRIFT/USD"}}
        row=make(stage(),canonical(),evidence(),approvals)[0]
        self.assertEqual(row["project_coingecko_contract_comparison"],"MATCH")
        self.assertEqual(row["project_coingecko_network_comparison"],"MATCH")
        self.assertEqual(row["exchange_canonical_comparison"],"UNKNOWN")
        self.assertEqual(row["final_decision"],"PENDING")

if __name__=="__main__":unittest.main()
