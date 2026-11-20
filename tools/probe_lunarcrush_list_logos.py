"""Research-only LunarCrush coin-list logo coverage probe (Light-plan safe).

Read archived disputed identities; retrieve list/v1 by numeric coin ID with
pagination, then optionally list/v2 for unresolved IDs, then meta/v1 for up
to three remaining IDs. Absence, missing pages, HTTP 402/429 and missing
fields are distinct statuses. Never write production mappings or alerts.
"""
import argparse
import csv
import json
import os
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from lunarcrush_client import LunarCrushClient

FIELDS = ("coin_id", "symbol", "name", "coingecko_id",
          "coingecko_logo_url", "lunarcrush_name", "lunarcrush_symbol",
          "lunarcrush_logo_url", "logo_source", "lookup_status",
          "name_status", "image_url_status", "reason",
          "production_approval", "alert_eligible")
DEFAULT_LIMIT = 1000


def targets_from_audit(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    selected = [r for r in rows if r.get("price_status") == "PRICE_CONFLICT_REVIEW"]
    ids = [str(r.get("coin_id") or "") for r in selected]
    if not ids or not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("Expected nonempty unique disputed LunarCrush IDs")
    return selected


def normalize(value):
    return " ".join(str(value or "").casefold().split())


def extract_page(payload, page):
    data = payload.get("data") if isinstance(payload, dict) else None
    config = payload.get("config") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not isinstance(config, dict):
        raise ValueError("Malformed LunarCrush list response")
    if "page" in config and int(config["page"]) != page:
        raise ValueError("Unexpected LunarCrush page")
    total = config.get("total_rows")
    if total is None or int(total) < 0:
        raise ValueError("Missing total_rows; cannot certify complete list coverage")
    return data, int(total)


def gather(client, version, target_ids, max_pages=20, limit=DEFAULT_LIMIT,
           pause=time.sleep):
    """Fetch full paginated inventory; do not equate a partial list with absence."""
    catalog, seen = {}, set()
    total = None
    for page in range(max_pages):
        if page:
            pause(0)  # LC client's own 10-rpm pacing applies.
        payload = client.get("/public/coins/list/" + version,
                             params={"limit":limit, "page":page})
        items, page_total = extract_page(payload, page)
        if total is None:
            total = page_total
        elif page_total != total:
            raise ValueError("List total changed while paging; incomplete snapshot")
        for coin in items:
            if not isinstance(coin, dict) or coin.get("id") is None:
                continue
            cid = str(coin["id"])
            if cid in seen:
                raise ValueError("Duplicate ID across LunarCrush pages")
            seen.add(cid)
            if cid in target_ids:
                catalog[cid] = coin
        if len(seen) >= total:
            return catalog, {"complete":True, "pages":page+1, "total":total,
                             "covered_ids":len(seen)}
        if not items:
            raise ValueError("Empty page before reported total_rows covered")
    raise ValueError(f"Exceeded max_pages={max_pages}; list coverage incomplete")


def evidence(target, entry, source, complete, message=""):
    row = {k:"" for k in FIELDS}
    row.update(coin_id=str(target["coin_id"]), symbol=target.get("symbol",""),
               name=target.get("lunarcrush_name",""),
               coingecko_id=target.get("coingecko_id",""),
               coingecko_logo_url=target.get("coingecko_logo_url",""),
               logo_source=source, lookup_status="NOT_FOUND" if complete else "SOURCE_UNAVAILABLE",
               image_url_status="NOT_CHECKED", name_status="NOT_CHECKED",
               reason=message, production_approval="NO", alert_eligible="NO")
    if entry is None:
        return row
    if str(entry.get("id") or "") != row["coin_id"]:
        row.update(lookup_status="IDENTITY_CONFLICT",reason="Numeric LC ID mismatch")
        return row
    row.update(lunarcrush_name=str(entry.get("name") or ""),
               lunarcrush_symbol=str(entry.get("symbol") or ""))
    if normalize(row["lunarcrush_name"]) != normalize(row["name"]) or (
         normalize(row["lunarcrush_symbol"]) != normalize(row["symbol"])):
        row.update(lookup_status="IDENTITY_CONFLICT",name_status="CONFLICT",
                   reason="Current LC name or symbol changed; image not used")
        return row
    row["name_status"] = "EXACT_NORMALIZED_NAME_SYMBOL"
    row["lookup_status"] = "FOUND"
    logo = entry.get("logo")
    row["lunarcrush_logo_url"] = str(logo) if isinstance(logo,str) else ""
    row["image_url_status"] = "URL_PRESENT" if row["lunarcrush_logo_url"] else "FIELD_EMPTY_OR_MISSING"
    return row


def execute(targets, client, output, try_v2=True, meta_limit=3,
            max_pages=20):
    ids = {str(t["coin_id"]) for t in targets}
    coverage, errors, catalogs = {}, {}, {}
    for version in ("v1", "v2"):
        if version == "v2" and not try_v2:
            continue
        if version == "v2" and "v1" in catalogs and all(
                catalogs["v1"].get(cid,{}).get("logo") for cid in ids):
            continue
        try:
            catalogs[version], coverage[version] = gather(
                client,version,ids,max_pages=max_pages)
        except Exception as exc:
            errors[version] = type(exc).__name__ + ": " + str(exc)[:120]
    results = []
    for target in targets:
        cid = str(target["coin_id"])
        row = None
        for version in ("v1","v2"):
            if version not in catalogs:
                continue
            check = evidence(target,catalogs[version].get(cid),
                             "coins/list/"+version,True)
            if row is None:
                row = check
            if check["lookup_status"] == "IDENTITY_CONFLICT":
                row = check
                break
            if check["lookup_status"] == "FOUND" and check["image_url_status"] == "URL_PRESENT":
                row = check
                break
            if check["lookup_status"] == "FOUND":
                row = check
        if row is None:
            row = evidence(target,None,"",False,"No complete coin-list response")
        results.append(row)
    # Probe meta/v1 only for a small, deterministic sample still lacking logos.
    missing = [r for r in results if r["image_url_status"] != "URL_PRESENT"
               and r["lookup_status"] != "IDENTITY_CONFLICT"]
    for row in missing[:meta_limit]:
        cid = row["coin_id"]
        try:
            payload = client.get("/public/coins/" + quote(cid,safe="") + "/meta/v1")
            candidate = payload.get("data") if isinstance(payload,dict) else None
            if not isinstance(candidate,dict):
                raise ValueError("Missing meta data object")
            # Meta can omit identity fields: never infer ID or override the
            # identity already established from list or archived cohort.
            if candidate.get("id") is not None and str(candidate["id"]) != cid:
                raise ValueError("Meta response ID conflict")
            if candidate.get("name") and normalize(candidate["name"]) != normalize(row["name"]):
                raise ValueError("Meta response name conflict")
            if candidate.get("symbol") and normalize(candidate["symbol"]) != normalize(row["symbol"]):
                raise ValueError("Meta response symbol conflict")
            row["reason"] = "meta/v1 logo field " + (
                "present" if candidate.get("logo") else "absent")
            if candidate.get("logo") and row["lookup_status"] == "FOUND":
                row["lunarcrush_logo_url"] = str(candidate["logo"])
                row["image_url_status"] = "URL_PRESENT"
                row["logo_source"] = "coins/meta/v1"
        except Exception as exc:
            row["reason"] = "meta/v1: " + type(exc).__name__ + " (not identity failure)"
    out = Path(output)
    out.mkdir(parents=True,exist_ok=True)
    with (out/"lunarcrush_logo_inventory.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,FIELDS)
        writer.writeheader()
        writer.writerows(results)
    stats={"target_coins":len(targets),
           "logo_urls_found":sum(x["image_url_status"]=="URL_PRESENT" for x in results),
           "name_matches":sum(x["name_status"]=="EXACT_NORMALIZED_NAME_SYMBOL" for x in results),
           "statuses":dict(Counter(x["image_url_status"] for x in results)),
           "sources":dict(Counter(x["logo_source"] for x in results)),
           "pagination":coverage,"source_errors":errors,
           "identity_verified":0,"production_approvals":0,"alerts":0,
           "note":"Research-only URLs; not downloaded or visually compared. Coin IDs, not tickers, are joins."}
    (out/"lunarcrush_logo_inventory.json").write_text(json.dumps(stats,indent=2)+"\n")
    return stats


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--audit",required=True)
    p.add_argument("--output",default="reports/lunarcrush_logo_probe")
    p.add_argument("--skip-v2",action="store_true")
    p.add_argument("--meta-limit",type=int,default=3)
    p.add_argument("--max-pages",type=int,default=20)
    args=p.parse_args()
    if args.meta_limit<0 or args.meta_limit>3 or args.max_pages<1 or args.max_pages>30:
        p.error("invalid controlled research limits")
    stats=execute(targets_from_audit(args.audit),LunarCrushClient(),args.output,
                  try_v2=not args.skip_v2,meta_limit=args.meta_limit,
                  max_pages=args.max_pages)
    print(json.dumps(stats,indent=2))


if __name__=="__main__":
    main()
