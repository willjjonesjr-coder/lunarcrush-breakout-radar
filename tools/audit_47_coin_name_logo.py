"""Research-only LunarCrush vs CoinGecko full-name and logo evidence audit.

A matching ticker/name/logo is supporting evidence, never canonical identity
proof. This module does not update approved registries, prices or alerts.
Only PRICE_CONFLICT_REVIEW coins from the 47-coin workflow are evaluated.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

CG_API = "https://api.coingecko.com/api/v3"
LC_API = "https://lunarcrush.com/api4"
ALLOWED_IMAGES = {"cdn.lunarcrush.com", "coin-images.coingecko.com",
                  "assets.coingecko.com"}
FIELDS = ("coin_id", "symbol", "lunarcrush_name", "lunarcrush_name_live",
          "coingecko_id", "coingecko_name", "name_status",
          "lunarcrush_logo_url", "coingecko_logo_url", "logo_status",
          "logo_sha256_lunarcrush", "logo_sha256_coingecko",
          "visual_difference_bits", "identity_status", "price_status",
          "contract_evidence", "reason", "production_approval", "alert_eligible")


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def exact_identity_candidate(catalog, name, symbol):
    """Never choose the first of multiple ticker/name matches."""
    matches = [c for c in catalog if normalize(c.get("name")) == normalize(name)
               and normalize(c.get("symbol")) == normalize(symbol)]
    if len(matches) != 1:
        return None, ("AMBIGUOUS_NAME_SYMBOL" if matches else "NO_NAME_SYMBOL_MATCH")
    return matches[0], "EXACT_NORMALIZED_NAME_SYMBOL"


def image_host_allowed(url):
    parsed = urlparse(str(url or ""))
    return (parsed.scheme == "https" and parsed.hostname in ALLOWED_IMAGES
            and not parsed.username and not parsed.password and not parsed.port
            and len(url) < 2048)


def fingerprint(url, image_get):
    """Return digest and a 64-bit difference hash; fail closed for unsafe URLs."""
    if not image_host_allowed(url):
        raise ValueError("unavailable or untrusted image host")
    raw = image_get(url)
    if len(raw) > 1_000_000 or not raw:
        raise ValueError("image missing or exceeds size limit")
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as source:
        if source.width * source.height > 2_000_000:
            raise ValueError("image dimensions exceed limit")
        image = source.convert("RGB").resize((9, 8))
        luminance = [round(.299*r + .587*g + .114*b) for r, g, b in image.getdata()]
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (luminance[y*9+x] > luminance[y*9+x+1])
    return hashlib.sha256(raw).hexdigest(), bits


def compare_logos(lunar_url, gecko_url, image_get):
    if not lunar_url or not gecko_url:
        return "LOGO_UNAVAILABLE", "", "", "", "Missing image from one provider"
    try:
        lunar_sha, lunar_bits = fingerprint(lunar_url, image_get)
        gecko_sha, gecko_bits = fingerprint(gecko_url, image_get)
    except (ValueError, OSError, TypeError) as exc:
        return "LOGO_UNAVAILABLE", "", "", "", type(exc).__name__
    distance = (lunar_bits ^ gecko_bits).bit_count()
    if lunar_sha == gecko_sha:
        status = "EXACT_LOGO_BYTES"
    elif distance <= 5:
        status = "POSSIBLE_VISUAL_MATCH"
    else:
        status = "LOGO_REVIEW_REQUIRED"
    return status, lunar_sha, gecko_sha, distance, "Visual similarity is not canonical identity verification"


def audit_one(item, catalog, coin_details, gecko_details, image_get):
    cid = str(item.get("coin_id") or "")
    name = str(item.get("name") or "")
    symbol = str(item.get("symbol") or "")
    row = dict.fromkeys(FIELDS, "")
    row.update(coin_id=cid, symbol=symbol, lunarcrush_name=name,
               price_status=item.get("corroboration_status", ""),
               name_status="NOT_CHECKED", logo_status="LOGO_UNAVAILABLE",
               identity_status="REVIEW_REQUIRED", production_approval="NO",
               alert_eligible="NO", contract_evidence="NOT_VERIFIED")
    candidate, status = exact_identity_candidate(catalog, name, symbol)
    row["name_status"] = status
    if candidate is None:
        row["reason"] = "No unique canonical full-name and ticker match; no logo-based lookup"
        return row
    row["coingecko_id"] = str(candidate.get("id") or "")
    if not row["coingecko_id"]:
        row["name_status"] = "MISSING_CANONICAL_ID"
        return row
    try:
        lc = coin_details(cid)
        if (str(lc.get("id") or "") != cid or
                normalize(lc.get("symbol")) != normalize(symbol)):
            row["name_status"] = "LUNARCRUSH_IDENTITY_CONFLICT"
            row["reason"] = "LunarCrush detail ID or ticker disagrees"
            return row
        row["lunarcrush_name_live"] = str(lc.get("name") or "")
        if normalize(lc.get("name")) != normalize(name):
            row["name_status"] = "LUNARCRUSH_NAME_CONFLICT"
            row["reason"] = "LunarCrush current name differs from archived cohort"
            return row
    except Exception:
        row["name_status"] = "LUNARCRUSH_LOOKUP_UNAVAILABLE"
        row["reason"] = "Current LunarCrush identity unavailable (missing key, gated endpoint or network)"
        return row
    try:
        cg = gecko_details(row["coingecko_id"])
        if (str(cg.get("id")) != row["coingecko_id"]
                or normalize(cg.get("symbol")) != normalize(symbol)
                or normalize(cg.get("name")) != normalize(name)):
            row["name_status"] = "COINGECKO_DETAIL_CONFLICT"
            row["reason"] = "CoinGecko details contradict the unique catalog identity"
            return row
        row["coingecko_name"] = str(cg.get("name") or "")
        row["name_status"] = "EXACT_NORMALIZED_NAME_SYMBOL"
        row["lunarcrush_logo_url"] = str(lc.get("logo") or "")
        images = cg.get("image") if isinstance(cg.get("image"), dict) else {}
        row["coingecko_logo_url"] = str(images.get("small") or images.get("thumb") or "")
        status, sha_lc, sha_cg, distance, reason = compare_logos(
            row["lunarcrush_logo_url"], row["coingecko_logo_url"], image_get)
        row.update(logo_status=status, logo_sha256_lunarcrush=sha_lc,
                   logo_sha256_coingecko=sha_cg, visual_difference_bits=distance,
                   reason=reason)
    except Exception:
        row["name_status"] = "COINGECKO_LOOKUP_UNAVAILABLE"
        row["reason"] = "CoinGecko metadata unavailable; no identity inference"
    return row


def run(price_csv, candidates_csv, out_dir, catalog, coin_details,
        gecko_details, image_get):
    with open(price_csv, newline="", encoding="utf-8") as f:
        prices = list(csv.DictReader(f))
    with open(candidates_csv, newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))
    lookup = {str(x["coin_id"]): x for x in candidates}
    if len(lookup) != len(candidates):
        raise ValueError("duplicate input coin IDs")
    selected = []
    for p in prices:
        if p.get("corroboration_status") != "PRICE_CONFLICT_REVIEW":
            continue
        cid = str(p.get("coin_id") or "")
        if cid not in lookup:
            raise ValueError("price-conflict coin absent from source cohort")
        selected.append({**lookup[cid], "corroboration_status": p["corroboration_status"]})
    if len({x["coin_id"] for x in selected}) != len(selected):
        raise ValueError("duplicate conflict coin IDs")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    findings = []
    for item in selected:
        row = audit_one(item, catalog, coin_details, gecko_details, image_get)
        findings.append(row)
        # Save intermediate evidence even if the next provider is unavailable.
        with (out/"name_logo_identity_audit.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            w.writerows(findings)
    if not selected:
        with (out/"name_logo_identity_audit.csv").open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, FIELDS).writeheader()
    summary = dict(candidates=len(selected),
                   name_statuses=dict(Counter(x["name_status"] for x in findings)),
                   logo_statuses=dict(Counter(x["logo_status"] for x in findings)),
                   identity_verified=0, production_approvals=0, alerts=0,
                   policy="Research-only supporting name/logo evidence; no automatic canonical identity approvals.")
    (out/"name_logo_identity_audit.json").write_text(json.dumps(summary, indent=2)+"\n")
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--price-summary", default="reports/47_cex_price_research/provisional_ema_summary.csv")
    p.add_argument("--candidates", default="reports/47_cex_research_input/candidates.csv")
    p.add_argument("--output", default="reports/47_cex_name_logo_audit")
    args = p.parse_args()
    import urllib.request
    from lunarcrush_client import LunarCrushClient
    from tools.ema_identity_evidence import fetch

    # Provider calls are deliberately bounded. No hardcoded coin IDs or approval.
    catalog = fetch(CG_API + "/coins/list")
    if not isinstance(catalog, list):
        raise ValueError("CoinGecko catalog lookup failed")
    lunar = LunarCrushClient() if os.getenv("LUNARCRUSH_API_KEY") else None

    def coin_details(cid):
        if lunar is None:
            raise RuntimeError("LunarCrush key unavailable")
        payload = lunar.get("/public/coins/" + quote(cid, safe="") + "/v1")
        return payload.get("data") or {}

    last_request = [0.0]
    def gecko_details(cid):
        delay = 6.2 - (time.monotonic() - last_request[0])
        if delay > 0:
            time.sleep(delay)
        last_request[0] = time.monotonic()
        return fetch(CG_API + "/coins/" + quote(cid, safe="") +
                     "?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false")

    def image_get(url):
        if not image_host_allowed(url):
            raise ValueError("image host not allowed")
        request = requests.get(url, timeout=10, allow_redirects=False,
                               headers={"Accept":"image/png,image/jpeg,image/webp"})
        request.raise_for_status()
        if int(request.headers.get("Content-Length") or 0) > 1_000_000:
            raise ValueError("oversized image")
        return request.content

    print(json.dumps(run(args.price_summary, args.candidates, args.output,
                         catalog, coin_details, gecko_details, image_get),
                     indent=2), flush=True)


if __name__ == "__main__":
    main()
