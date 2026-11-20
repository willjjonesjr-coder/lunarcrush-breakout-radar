"""Independent CoinGecko/CoinMarketCap logo comparison for prior identity-conflict research.

The source input is the existing full-name/ticker audit CSV; no price collection
or production modification. Neither ticker nor logo similarity verifies contract.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import requests

from tools.audit_47_coin_name_logo import normalize

CMC = "https://pro-api.coinmarketcap.com/public-api"
HOSTS = {"coin-images.coingecko.com", "assets.coingecko.com",
         "s2.coinmarketcap.com", "s3.coinmarketcap.com"}
COLUMNS = ("coin_id", "symbol", "lunarcrush_name", "coingecko_id", "cmc_id",
           "cmc_name", "name_status", "coingecko_logo_url", "cmc_logo_url",
           "logo_status", "coingecko_sha256", "cmc_sha256",
           "perceptual_distance", "mean_rgb_distance", "reason",
           "price_status", "identity_status", "production_approval",
           "alert_eligible", "canonical_contract_status")


def selected_rows(rows, expected=12):
    """Only the prior audit's unique name + ticker matches with CG image URLs."""
    ids = [str(r.get("coin_id", "")) for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate LunarCrush IDs in source audit")
    matches = [r for r in rows
               if r.get("price_status") == "PRICE_CONFLICT_REVIEW"
               and r.get("name_status") == "EXACT_NORMALIZED_NAME_SYMBOL"
               and r.get("coingecko_id") and r.get("coingecko_logo_url")]
    if len(matches) != expected:
        raise ValueError(f"Expected {expected} unique prior name matches, got {len(matches)}")
    return matches


def cmc_unique_map(records, name, symbol):
    """Never pick a logo from an arbitrary first ticker match."""
    hits = [r for r in records if normalize(r.get("name")) == normalize(name)
            and normalize(r.get("symbol")) == normalize(symbol)]
    if not hits:
        return None, "CMC_NAME_SYMBOL_NOT_FOUND"
    if len(hits) != 1 or not str(hits[0].get("id", "")).isdigit():
        return None, "CMC_ID_AMBIGUOUS"
    return hits[0], "EXACT_NORMALIZED_NAME_SYMBOL"


def cmc_detail(data, cid):
    """Parse CMC info response keyed by stable numeric ID and confirm identity."""
    payload = data.get("data", {})
    item = payload.get(str(cid)) if isinstance(payload, dict) else None
    if isinstance(item, list):
        if len(item) != 1:
            raise ValueError("Ambiguous CMC metadata ID")
        item = item[0]
    if not isinstance(item, dict) or str(item.get("id")) != str(cid):
        raise ValueError("CMC metadata ID mismatch or unavailable")
    return item


def safe_logo_url(url):
    try:
        p = urlparse(str(url or ""))
        return (p.scheme == "https" and p.hostname in HOSTS and p.port is None
                and p.username is None and p.password is None
                and len(str(url)) < 2048)
    except ValueError:
        return False


def fingerprint(url, image_bytes):
    if not safe_logo_url(url):
        raise ValueError("image host untrusted or image URL missing")
    raw = image_bytes(url)
    if not raw or len(raw) > 1_000_000:
        raise ValueError("image empty or oversized")
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as original:
        if original.width * original.height > 2_000_000:
            raise ValueError("unsafe image dimensions")
        rgba = original.convert("RGBA")
        backdrop = Image.new("RGBA", rgba.size, (255,255,255,255))
        backdrop.alpha_composite(rgba)
        rgb = backdrop.convert("RGB").resize((9,8))
        values = list(rgb.getdata())
    lum = [int(.299*r+.587*g+.114*b) for r,g,b in values]
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (lum[y*9+x] > lum[y*9+x+1])
    average = tuple(sum(v[channel] for v in values)/len(values) for channel in range(3))
    return hashlib.sha256(raw).hexdigest(), bits, average


def compare_images(gecko_url, cmc_url, image_bytes):
    if not gecko_url or not cmc_url:
        return dict(logo_status="IMAGE_URL_MISSING", reason="One provider has no image URL")
    if not safe_logo_url(gecko_url) or not safe_logo_url(cmc_url):
        return dict(logo_status="IMAGE_HOST_UNTRUSTED", reason="Image host outside allowlist")
    try:
        ga, gb, gmean = fingerprint(gecko_url, image_bytes)
    except Exception as exc:
        return dict(logo_status="COINGECKO_IMAGE_DOWNLOAD_ERROR",
                    reason=type(exc).__name__)
    try:
        ca, cb, cmean = fingerprint(cmc_url, image_bytes)
    except Exception as exc:
        return dict(logo_status="CMC_IMAGE_DOWNLOAD_ERROR", reason=type(exc).__name__)
    distance = (gb ^ cb).bit_count()
    mean_distance = sum((x-y)**2 for x,y in zip(gmean,cmean))**.5
    state = ("EXACT_IMAGE_BYTES" if ga == ca else
             "POSSIBLE_VISUAL_MATCH" if distance <= 5 and mean_distance <= 35 else
             "LOGO_REVIEW_REQUIRED")
    return dict(logo_status=state, reason="Visual evidence only; not canonical identity",
                coingecko_sha256=ga, cmc_sha256=ca,
                perceptual_distance=distance, mean_rgb_distance=round(mean_distance,2))


def evaluate(row, map_lookup, detail_lookup, image_bytes):
    item = {key:"" for key in COLUMNS}
    item.update(coin_id=row["coin_id"], symbol=row["symbol"],
                lunarcrush_name=row["lunarcrush_name"], coingecko_id=row["coingecko_id"],
                coingecko_logo_url=row["coingecko_logo_url"],
                price_status=row["price_status"], identity_status="REVIEW_REQUIRED",
                production_approval="NO", alert_eligible="NO",
                canonical_contract_status="NOT_VERIFIED",
                name_status="NOT_CHECKED", logo_status="NOT_CHECKED")
    try:
        mapping = map_lookup(row["symbol"])
        records = mapping.get("data") if isinstance(mapping, dict) else None
        if not isinstance(records, list):
            raise ValueError("CMC mapping unavailable")
        match, status = cmc_unique_map(records, row["lunarcrush_name"], row["symbol"])
        item["name_status"] = status
        if match is None:
            item.update(logo_status="NOT_CHECKED", reason="No unique name and symbol")
            return item
        cid = str(match["id"])
        metadata = cmc_detail(detail_lookup(cid), cid)
        if (normalize(metadata.get("name")) != normalize(row["lunarcrush_name"])
                or normalize(metadata.get("symbol")) != normalize(row["symbol"])):
            item.update(name_status="CMC_METADATA_CONFLICT", logo_status="NOT_CHECKED",
                        reason="CMC metadata contradicts ID map")
            return item
        item.update(cmc_id=cid, cmc_name=metadata["name"],
                    name_status="EXACT_NORMALIZED_NAME_SYMBOL",
                    cmc_logo_url=str(metadata.get("logo") or ""))
    except Exception as exc:
        item.update(name_status="CMC_LOOKUP_ERROR", logo_status="NOT_CHECKED",
                    reason=type(exc).__name__)
        return item
    item.update(compare_images(item["coingecko_logo_url"],
                               item["cmc_logo_url"], image_bytes))
    return item


def write(rows, out_dir, map_lookup, detail_lookup, image_bytes, expected=12):
    subset = selected_rows(rows, expected)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    findings = []
    for entry in subset:
        findings.append(evaluate(entry, map_lookup, detail_lookup, image_bytes))
        # Checkpoint results after each candidate.
        with (out/"provider_logo_comparison.csv").open("w",newline="",encoding="utf-8") as f:
            w = csv.DictWriter(f,COLUMNS)
            w.writeheader()
            w.writerows(findings)
    result = dict(candidates=len(subset),
                  name_statuses=dict(Counter(r["name_status"] for r in findings)),
                  logo_statuses=dict(Counter(r["logo_status"] for r in findings)),
                  identity_verified=0, production_approvals=0, alerts=0,
                  source="Prior 47-coin name/logo audit; only exact CoinGecko name/symbol matches.",
                  policy="Provider logo comparison is supporting evidence only, not contract verification.")
    (out/"provider_logo_comparison.json").write_text(json.dumps(result,indent=2)+"\n")
    return result


class Provider:
    def __init__(self, cache):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True,exist_ok=True)
        self.last = 0.0

    def get(self, url, params=None, binary=False):
        cache_key = hashlib.sha256(json.dumps([url,params],sort_keys=True).encode()).hexdigest()
        path = self.cache/(cache_key+(".img" if binary else ".json"))
        if path.exists() and time.time()-path.stat().st_mtime < 86400:
            return path.read_bytes() if binary else json.loads(path.read_text())
        # Pace all keyless requests, retaining failures as errors rather than matching.
        delay = 2.5-(time.monotonic()-self.last)
        if delay > 0:
            time.sleep(delay)
        for attempt in range(3):
            self.last=time.monotonic()
            response=requests.get(url,params=params,timeout=18,allow_redirects=False,
                                  headers={"Accept":"image/png,image/jpeg,image/webp" if binary else "application/json"},
                                  stream=True)
            try:
                if response.status_code == 429 and attempt < 2:
                    time.sleep(5*2**attempt)
                    continue
                response.raise_for_status()
                if response.is_redirect:
                    raise ValueError("provider redirect not allowed")
                if binary:
                    if not str(response.headers.get("Content-Type","")).lower().startswith("image/"):
                        raise ValueError("unexpected image content type")
                    data=bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data)>1_000_000:
                            raise ValueError("image size limit exceeded")
                    content=bytes(data)
                    path.write_bytes(content)
                    return content
                obj=response.json()
                status=obj.get("status") if isinstance(obj,dict) else None
                if isinstance(status,dict) and status.get("error_code") not in (0,None):
                    raise ValueError("CMC API returned error")
                path.write_text(json.dumps(obj))
                return obj
            finally:
                response.close()
        raise RuntimeError("API rate limit retry exhausted")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",required=True,help="Prior identity audit CSV")
    parser.add_argument("--output",default="reports/cmc_logo_comparison")
    parser.add_argument("--cache",default="reports/logo_metadata_cache")
    parser.add_argument("--expected",type=int,default=12)
    args=parser.parse_args()
    with open(args.source,newline="",encoding="utf-8") as f:
        rows=list(csv.DictReader(f))
    provider=Provider(args.cache)
    def lookup(symbol):
        return provider.get(CMC+"/v1/cryptocurrency/map",{"symbol":symbol})
    def detail(cid):
        return provider.get(CMC+"/v2/cryptocurrency/info",{"id":cid})
    summary=write(rows,args.output,lookup,detail,lambda url:provider.get(url,binary=True),
                  expected=args.expected)
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
