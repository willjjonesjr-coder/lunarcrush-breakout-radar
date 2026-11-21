"""No-network independent logo identity research regressions."""
import csv
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from tools.compare_independent_coin_logos import (
    selected_rows, cmc_unique_map, cmc_detail, compare_images,
    evaluate, write, safe_logo_url,
)

CG = "https://coin-images.coingecko.com/coins/images/1/small/abc.png"
CMC_IMG = "https://s2.coinmarketcap.com/static/img/coins/64x64/12.png"


def png(color=(60, 120, 180)):
    img = Image.new("RGB", (24,24), color)
    memory = io.BytesIO()
    img.save(memory, format="PNG")
    return memory.getvalue()


def row(cid="12", status="EXACT_NORMALIZED_NAME_SYMBOL", logo=CG):
    return dict(coin_id=cid, symbol="ABC", lunarcrush_name="Example Coin",
                coingecko_id="example-coin", coingecko_logo_url=logo,
                name_status=status, price_status="PRICE_CONFLICT_REVIEW")


def mapping(symbol):
    return {"data":[{"id":12,"name":"Example Coin","symbol":symbol}]}


def detail(cid):
    return {"data":{str(cid):{"id":int(cid),"name":"Example Coin",
                              "symbol":"ABC","logo":CMC_IMG}}}


class IndependentLogoTests(unittest.TestCase):
    def test_only_unique_gecko_matches_with_real_image_urls(self):
        rows=[row(),row("2",status="AMBIGUOUS_NAME_SYMBOL"),
              row("3",logo=""),row("4",status="NO_NAME_SYMBOL_MATCH")]
        self.assertEqual([r["coin_id"] for r in selected_rows(rows,1)], ["12"])
        with self.assertRaisesRegex(ValueError,"Expected"):
            selected_rows(rows,2)
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            selected_rows(rows+[row()],1)

    def test_cmc_name_symbol_must_be_unique(self):
        m={"id":12,"name":"Example Coin","symbol":"ABC"}
        self.assertEqual(cmc_unique_map([m]," example  COIN ","abc")[1],
                         "EXACT_NORMALIZED_NAME_SYMBOL")
        self.assertEqual(cmc_unique_map([m,m],"Example Coin","ABC")[1],
                         "CMC_ID_AMBIGUOUS")
        self.assertEqual(cmc_unique_map([m],"Different Coin","ABC")[1],
                         "CMC_NAME_SYMBOL_NOT_FOUND")
        with self.assertRaisesRegex(ValueError,"mismatch"):
            cmc_detail({"data":{"12":{"id":13}}},12)

    def test_exact_image_matching_does_not_grant_approval(self):
        result=evaluate(row(),mapping,detail,lambda url:png())
        self.assertEqual(result["logo_status"],"EXACT_IMAGE_BYTES")
        self.assertEqual(result["name_status"],"EXACT_NORMALIZED_NAME_SYMBOL")
        self.assertEqual(result["production_approval"],"NO")
        self.assertEqual(result["alert_eligible"],"NO")
        self.assertEqual(result["identity_status"],"REVIEW_REQUIRED")
        self.assertEqual(result["canonical_contract_status"],"NOT_VERIFIED")

    def test_different_images_are_flagged_for_review(self):
        result=compare_images(CG,CMC_IMG,lambda url:png((0,0,0)) if url==CG else png((255,255,255)))
        self.assertEqual(result["logo_status"],"LOGO_REVIEW_REQUIRED")
        self.assertGreater(result["mean_rgb_distance"],35)

    def test_untrusted_host_and_image_errors_separate(self):
        self.assertFalse(safe_logo_url("http://s2.coinmarketcap.com/x.png"))
        self.assertFalse(safe_logo_url("https://s2.coinmarketcap.com.evil.test/img.png"))
        self.assertFalse(safe_logo_url("https://127.0.0.1/file"))
        bad=compare_images(CG,"https://evil.test/a.png",lambda url:png())
        self.assertEqual(bad["logo_status"],"IMAGE_HOST_UNTRUSTED")
        missing=compare_images(CG,"",lambda url:png())
        self.assertEqual(missing["logo_status"],"IMAGE_URL_MISSING")
        bad_cmc=compare_images(CG,CMC_IMG,
                               lambda url: png() if url==CG else (_ for _ in ()).throw(OSError()))
        self.assertEqual(bad_cmc["logo_status"],"CMC_IMAGE_DOWNLOAD_ERROR")

    def test_ambiguous_cmc_candidates_never_get_logo_or_approval(self):
        result=evaluate(row(),lambda _:{"data":[{"id":12,"name":"Example Coin","symbol":"ABC"},
                                                   {"id":13,"name":"Example Coin","symbol":"ABC"}]},
                        detail,lambda url:png())
        self.assertEqual(result["name_status"],"CMC_ID_AMBIGUOUS")
        self.assertEqual(result["logo_status"],"NOT_CHECKED")
        self.assertEqual(result["production_approval"],"NO")

    def test_metadata_disagreement_fail_closed(self):
        result=evaluate(row(),mapping,lambda _:{"data":{"12":{"id":12,"name":"Wrong","symbol":"ABC",
                                                           "logo":CMC_IMG}}},lambda url:png())
        self.assertEqual(result["name_status"],"CMC_METADATA_CONFLICT")
        self.assertEqual(result["production_approval"],"NO")

    def test_checkpoint_csv_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary=write([row()],Path(tmp),mapping,detail,lambda url:png(),expected=1)
            self.assertEqual(summary["candidates"],1)
            self.assertEqual(summary["identity_verified"],0)
            with (Path(tmp)/"provider_logo_comparison.csv").open(newline="") as f:
                results=list(csv.DictReader(f))
            self.assertEqual(results[0]["coin_id"],"12")
            self.assertEqual(results[0]["logo_status"],"EXACT_IMAGE_BYTES")


if __name__=="__main__":
    unittest.main()
