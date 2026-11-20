"""Offline tests for exact-ID LunarCrush/CoinGecko branding comparison."""
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tools.compare_lunarcrush_coingecko_logos import (
    compare, trusted, reconcile, write, fingerprint, ImageClient, ImageDownloadError,
)


def image_bytes(color=(40, 80, 160)):
    img = Image.new("RGB", (24, 24), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def prior(cid, matched=True):
    return {"coin_id":cid, "symbol":"ABC", "lunarcrush_name":"Example Coin",
            "name_status":"EXACT_NORMALIZED_NAME_SYMBOL" if matched else "AMBIGUOUS_NAME_SYMBOL",
            "price_status":"PRICE_CONFLICT_REVIEW",
            "coingecko_id":"example-coin" if matched else "",
            "coingecko_logo_url":"https://coin-images.coingecko.com/a.png" if matched else ""}


def inventory(cid):
    return {"coin_id":cid,"symbol":"ABC","name":"Example Coin",
            "lookup_status":"FOUND","name_status":"EXACT_NORMALIZED_NAME_SYMBOL",
            "lunarcrush_logo_url":"https://cdn.lunarcrush.com/a.png"}


class LogoTests(unittest.TestCase):
    def test_allowed_urls_only(self):
        self.assertTrue(trusted("https://cdn.lunarcrush.com/a.png"))
        self.assertFalse(trusted("https://cdn.lunarcrush.com.bad.test/a.png"))
        self.assertFalse(trusted("http://coin-images.coingecko.com/a.png"))
        self.assertFalse(trusted("https://127.0.0.1/a.png"))
        self.assertFalse(trusted("https://cdn.lunarcrush.com:123/a.png"))

    def test_image_exact_and_distinct_solid_colors(self):
        urls=("https://cdn.lunarcrush.com/a.png","https://coin-images.coingecko.com/b.png")
        same=compare(*urls,lambda _:image_bytes())
        self.assertEqual(same["logo_status"],"EXACT_IMAGE_BYTES")
        different=compare(*urls,lambda u:image_bytes((5,5,5))
                          if "lunarcrush" in u else image_bytes((245,245,245)))
        self.assertEqual(different["logo_status"],"LOGO_REVIEW_REQUIRED")

    def test_missing_url_and_provider_specific_errors(self):
        urls=("https://cdn.lunarcrush.com/a.png","https://coin-images.coingecko.com/b.png")
        self.assertEqual(compare(urls[0],"",lambda _:image_bytes())["logo_status"],"IMAGE_URL_MISSING")
        self.assertEqual(compare("https://unsafe.test/a",urls[1],lambda _:image_bytes())["logo_status"],
                         "IMAGE_HOST_UNTRUSTED")
        def bad(u):
            if "lunarcrush" in u:
                raise OSError("offline")
            return image_bytes()
        self.assertEqual(compare(*urls,bad)["logo_status"],"LUNARCRUSH_IMAGE_ERROR")
        def bad_gecko(u):
            if "coingecko" in u:
                raise OSError("offline")
            return image_bytes()
        self.assertEqual(compare(*urls,bad_gecko)["logo_status"],"COINGECKO_IMAGE_ERROR")

    def test_unresolved_identity_is_separate_and_never_compared(self):
        p={"1":prior("1"),"2":prior("2",False)}
        i={"1":inventory("1"),"2":inventory("2")}
        seen=[]
        results=reconcile(i,p,lambda u:(seen.append(u),image_bytes())[1],
                          expected=2,expected_matches=1)
        self.assertEqual(len(seen),2)
        self.assertEqual(results[1]["logo_status"],"COINGECKO_IDENTITY_UNRESOLVED")
        self.assertTrue(all(r["production_approval"]=="NO" for r in results))
        self.assertTrue(all(r["identity_status"]=="REVIEW_REQUIRED" for r in results))

    def test_mismatched_ids_or_cohorts_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"cohort"):
            reconcile({"1":inventory("1")},{"2":prior("2")},
                      lambda _:image_bytes(),expected=1,expected_matches=1)
        with self.assertRaisesRegex(ValueError,"name/symbol"):
            a=inventory("1");a["symbol"]="OTHER"
            reconcile({"1":a},{"1":prior("1")},lambda _:image_bytes(),
                      expected=1,expected_matches=1)

    def test_csv_reports_are_research_only(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            input_rows=[(directory/"inventory.csv",[inventory("1")]),
                        (directory/"prior.csv",[prior("1")])]
            for filename,items in input_rows:
                with filename.open("w",newline="") as f:
                    writer=csv.DictWriter(f,items[0].keys())
                    writer.writeheader();writer.writerows(items)
            stats=write(directory/"inventory.csv", directory/"prior.csv",
                        directory/"output",lambda _:image_bytes(),
                        expected=1,expected_matches=1)
            self.assertEqual(stats["images_compared"],1)
            self.assertEqual(stats["production_approvals"],0)
            self.assertTrue((directory/"output"/"lunarcrush_coingecko_logo_comparison.csv").exists())

    def test_allowlisted_redirect_and_byte_validation(self):
        class Response:
            def __init__(self, status, headers=None, data=b""):
                self.status_code = status
                self.headers = headers or {}
                self.data = data
            def iter_content(self, size):
                yield self.data
            def close(self):
                pass
        target = "https://cdn.lunarcrush.com/terra.png"
        final = "https://cdn.lunarcrush.com/assets/terra.png"
        calls = []
        def request(url, **kwargs):
            calls.append((url, kwargs["allow_redirects"]))
            if url == target:
                return Response(302, {"Location": "/assets/terra.png"})
            return Response(200, {"Content-Type": "image/png"}, image_bytes())
        with tempfile.TemporaryDirectory() as root, patch(
            "tools.compare_lunarcrush_coingecko_logos.requests.get", side_effect=request):
            data = ImageClient(root).get(target)
        self.assertEqual(data, image_bytes())
        self.assertEqual(calls, [(target, False), (final, False)])

    def test_cross_origin_redirect_remains_blocked_with_diagnostic(self):
        class Redirect:
            status_code = 302
            headers = {"Location":"https://untrusted.example/terra.png"}
            def close(self): pass
        with tempfile.TemporaryDirectory() as root, patch(
            "tools.compare_lunarcrush_coingecko_logos.requests.get",
            return_value=Redirect()):
            with self.assertRaisesRegex(ImageDownloadError, "REDIRECT_UNTRUSTED"):
                ImageClient(root).get("https://cdn.lunarcrush.com/terra.png")

    def test_http_error_and_invalid_image_have_specific_reasons(self):
        class Response:
            def __init__(self, status, media, data):
                self.status_code = status
                self.headers = {"Content-Type":media}
                self.data = data
            def iter_content(self, size): yield self.data
            def close(self): pass
        target = "https://cdn.lunarcrush.com/terra.png"
        with tempfile.TemporaryDirectory() as root, patch(
            "tools.compare_lunarcrush_coingecko_logos.requests.get",
            return_value=Response(403,"text/html",b"denied")):
            with self.assertRaisesRegex(ImageDownloadError, "HTTP_403"):
                ImageClient(root).get(target)
        with tempfile.TemporaryDirectory() as root, patch(
            "tools.compare_lunarcrush_coingecko_logos.requests.get",
            return_value=Response(200,"image/png",b"not-a-png")):
            with self.assertRaisesRegex(ImageDownloadError, "IMAGE_DECODE"):
                ImageClient(root).get(target)


if __name__=="__main__":
    unittest.main()
