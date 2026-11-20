"""Offline LunarCrush logo-list pagination and identity safety tests."""
import csv
import tempfile
import unittest
from pathlib import Path

from tools.probe_lunarcrush_list_logos import (
    extract_page, gather, evidence, execute, targets_from_audit
)


def coin(i,logo="https://cdn.lunarcrush.com/a.png"):
    return {"id":i,"name":f"Coin {i}","symbol":f"C{i}","logo":logo}


def target(i):
    return {"coin_id":str(i),"lunarcrush_name":f"Coin {i}","symbol":f"C{i}",
            "coingecko_id":f"coin-{i}","coingecko_logo_url":"https://coin-images.coingecko.com/coin.png",
            "price_status":"PRICE_CONFLICT_REVIEW"}


class Client:
    def __init__(self,pages,meta=None):
        self.pages=pages
        self.meta=meta or {}
        self.calls=[]

    def get(self,path,params=None):
        self.calls.append((path,params))
        if "list/" in path:
            version=path.rsplit("/",1)[1]
            page=params["page"]
            result=self.pages.get((version,page))
            if isinstance(result,Exception):
                raise result
            if result is None:
                raise ValueError("No stub")
            return result
        cid=path.split("/")[-3]
        return {"data":self.meta.get(cid,{})}


def page(index,items,total):
    return {"data":items,"config":{"page":index,"total_rows":total}}


class ProbeTests(unittest.TestCase):
    def test_paginate_full_coverage_and_join_only_numeric_id(self):
        client=Client({("v1",0):page(0,[coin(1),coin(2)],3),
                       ("v1",1):page(1,[coin(3)],3)})
        catalog,stats=gather(client,"v1",{"3"},max_pages=3,limit=2)
        self.assertEqual(set(catalog),{"3"})
        self.assertTrue(stats["complete"])
        self.assertEqual(stats["pages"],2)
        self.assertEqual(catalog["3"]["logo"],coin(3)["logo"])

    def test_truncated_listing_not_misclassified_as_missing(self):
        client=Client({("v1",0):page(0,[coin(1)],4)})
        with self.assertRaisesRegex(ValueError,"Exceeded"):
            gather(client,"v1",{"4"},max_pages=1)

    def test_duplicate_crosspage_and_malformed_total_fail_closed(self):
        client=Client({("v1",0):page(0,[coin(1)],2),
                       ("v1",1):page(1,[coin(1)],2)})
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            gather(client,"v1",{"1"},max_pages=3)
        with self.assertRaisesRegex(ValueError,"total_rows"):
            extract_page({"data":[coin(1)],"config":{"page":0}},0)

    def test_fullname_ticker_conflict_blocks_image(self):
        result=evidence(target(1),{"id":1,"name":"Other","symbol":"C1",
                                     "logo":"https://cdn.lunarcrush.com/x.png"},
                        "coins/list/v1",True)
        self.assertEqual(result["lookup_status"],"IDENTITY_CONFLICT")
        self.assertFalse(result["lunarcrush_logo_url"])
        self.assertEqual(result["production_approval"],"NO")

    def test_v1_logo_preferred_without_v2_or_meta(self):
        client=Client({("v1",0):page(0,[coin(1)],1)})
        with tempfile.TemporaryDirectory() as tmp:
            stats=execute([target(1)],client,tmp,meta_limit=1)
            self.assertEqual(stats["logo_urls_found"],1)
            self.assertEqual(len(client.calls),1)
            with (Path(tmp)/"lunarcrush_logo_inventory.csv").open() as f:
                entry=list(csv.DictReader(f))[0]
            self.assertEqual(entry["logo_source"],"coins/list/v1")
            self.assertEqual(entry["production_approval"],"NO")

    def test_v2_fallback_recovers_missing_v1_logo(self):
        client=Client({("v1",0):page(0,[coin(1,"")],1),
                       ("v2",0):page(0,[coin(1)],1)})
        with tempfile.TemporaryDirectory() as tmp:
            stats=execute([target(1)],client,tmp)
        self.assertEqual(stats["logo_urls_found"],1)
        self.assertEqual(stats["sources"]["coins/list/v2"],1)

    def test_402_v2_does_not_destroy_v1_evidence(self):
        client=Client({("v1",0):page(0,[coin(1,"")],1),
                       ("v2",0):PermissionError("402")})
        with tempfile.TemporaryDirectory() as tmp:
            stats=execute([target(1)],client,tmp,meta_limit=0)
        self.assertEqual(stats["name_matches"],1)
        self.assertEqual(stats["logo_urls_found"],0)
        self.assertIn("v2",stats["source_errors"])

    def test_meta_research_is_bounded_and_does_not_infer_identity(self):
        client=Client({("v1",0):page(0,[coin(1,""),coin(2,""),coin(3,"")],3)},
                      meta={"1":{"logo":"https://cdn.lunarcrush.com/1.png"}})
        with tempfile.TemporaryDirectory() as tmp:
            stats=execute([target(1),target(2),target(3)],client,tmp,
                          try_v2=False,meta_limit=1)
        self.assertEqual(sum("meta/v1" in p for p,_ in client.calls),1)
        self.assertEqual(stats["logo_urls_found"],1)

    def test_only_conflict_rows_and_unique_ids_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"audit.csv"
            with path.open("w",newline="") as f:
                w=csv.DictWriter(f,["coin_id","price_status","symbol"])
                w.writeheader()
                w.writerows([{"coin_id":"1","price_status":"PRICE_CONFLICT_REVIEW"},
                             {"coin_id":"2","price_status":"PRICE_CORROBORATED_PRIMARY_TWO"}])
            self.assertEqual(len(targets_from_audit(path)),1)


if __name__=="__main__":
    unittest.main()
