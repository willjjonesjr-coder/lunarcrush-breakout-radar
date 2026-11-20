"""Offline tests for conflict-only, fail-closed full-name/logo research."""
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from tools.audit_47_coin_name_logo import (
    exact_identity_candidate, image_host_allowed, compare_logos, audit_one, run
)


def png(value=20):
    img = Image.new("RGB", (32,32), (value,80,120))
    file = io.BytesIO()
    img.save(file, format="PNG")
    return file.getvalue()


class NameLogoIdentityTests(unittest.TestCase):
    def setUp(self):
        self.coin = {"coin_id":"123", "symbol":"ABC", "name":"Example Coin",
                     "corroboration_status":"PRICE_CONFLICT_REVIEW"}
        self.catalog = [{"id":"example-coin","name":"Example Coin","symbol":"ABC"}]
        self.lunar = lambda cid: {"id":123,"name":"Example Coin","symbol":"ABC",
                                  "logo":"https://cdn.lunarcrush.com/example.png"}
        self.gecko = lambda cid: {"id":"example-coin","name":"Example Coin",
                                  "symbol":"ABC","image":{"small":"https://coin-images.coingecko.com/x.png"}}
        self.images = lambda url: png()

    def test_normalized_name_and_ticker_are_both_required_and_unique(self):
        coin, status = exact_identity_candidate(self.catalog, " example  COIN ", "abc")
        self.assertEqual(status, "EXACT_NORMALIZED_NAME_SYMBOL")
        self.assertEqual(coin["id"], "example-coin")
        self.assertIsNone(exact_identity_candidate(self.catalog, "Other Coin", "ABC")[0])
        self.assertEqual(exact_identity_candidate(self.catalog * 2, "Example Coin", "ABC")[1],
                         "AMBIGUOUS_NAME_SYMBOL")

    def test_exact_logo_matching_only_supports_research(self):
        row = audit_one(self.coin, self.catalog, self.lunar, self.gecko, self.images)
        self.assertEqual(row["name_status"], "EXACT_NORMALIZED_NAME_SYMBOL")
        self.assertEqual(row["logo_status"], "EXACT_LOGO_BYTES")
        self.assertEqual(row["identity_status"], "REVIEW_REQUIRED")
        self.assertEqual(row["production_approval"], "NO")
        self.assertEqual(row["alert_eligible"], "NO")
        self.assertTrue(row["logo_sha256_lunarcrush"])

    def test_no_inferred_logo_match_from_wrong_or_unsafe_urls(self):
        self.assertFalse(image_host_allowed("http://cdn.lunarcrush.com/x.png"))
        self.assertFalse(image_host_allowed("https://cdn.lunarcrush.com.evil.test/x.png"))
        self.assertFalse(image_host_allowed("https://127.0.0.1/x"))
        row = audit_one(self.coin, self.catalog, self.lunar,
                        lambda _: {**self.gecko(""), "image":{"small":"https://unsafe.test/logo.png"}},
                        self.images)
        self.assertEqual(row["logo_status"], "LOGO_UNAVAILABLE")
        self.assertEqual(row["production_approval"], "NO")

    def test_missing_lunarcrush_key_is_not_identity_failure_or_match(self):
        def blocked(cid):
            raise RuntimeError("key not available")
        row = audit_one(self.coin, self.catalog, blocked, self.gecko, self.images)
        self.assertEqual(row["name_status"], "LUNARCRUSH_LOOKUP_UNAVAILABLE")
        self.assertEqual(row["logo_status"], "LOGO_UNAVAILABLE")
        self.assertEqual(row["identity_status"], "REVIEW_REQUIRED")

    def test_conflicting_provider_names_fail_closed(self):
        wrong = lambda cid: {"id":123,"name":"Different Token","symbol":"ABC",
                             "logo":"https://cdn.lunarcrush.com/example.png"}
        row = audit_one(self.coin, self.catalog, wrong, self.gecko, self.images)
        self.assertEqual(row["name_status"], "LUNARCRUSH_NAME_CONFLICT")
        self.assertEqual(row["production_approval"], "NO")

    def test_only_price_conflicts_selected_and_no_automatic_approval(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            price = root/"price.csv"
            candidates = root/"candidates.csv"
            with candidates.open("w",newline="") as f:
                w=csv.DictWriter(f, ["coin_id","symbol","name"])
                w.writeheader()
                w.writerows([{"coin_id":"123","symbol":"ABC","name":"Example Coin"},
                             {"coin_id":"124","symbol":"XYZ","name":"Other"}])
            with price.open("w",newline="") as f:
                w=csv.DictWriter(f, ["coin_id","corroboration_status"])
                w.writeheader()
                w.writerows([{"coin_id":"123","corroboration_status":"PRICE_CONFLICT_REVIEW"},
                             {"coin_id":"124","corroboration_status":"PRICE_CORROBORATED_PRIMARY_TWO"}])
            stats = run(price,candidates,root/"out",self.catalog,self.lunar,
                        self.gecko,self.images)
            self.assertEqual(stats["candidates"],1)
            self.assertEqual(stats["production_approvals"],0)
            with (root/"out"/"name_logo_identity_audit.csv").open() as f:
                rows=list(csv.DictReader(f))
            self.assertEqual([r["coin_id"] for r in rows], ["123"])


if __name__ == "__main__":
    unittest.main()
