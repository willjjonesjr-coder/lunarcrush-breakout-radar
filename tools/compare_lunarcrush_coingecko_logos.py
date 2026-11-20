"""Compare archived LunarCrush list/v1 logos with archived CoinGecko URLs.

Research only. Exact numeric LC ID joins, unique canonical CG name/symbol
matching from upstream artifact, distinct unresolved rows, never auto-approve.
"""
import argparse
import csv
import hashlib
import io
import json
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

HOSTS = {"cdn.lunarcrush.com", "coin-images.coingecko.com", "assets.coingecko.com"}
FIELDS = ("coin_id", "symbol", "name", "lunarcrush_logo_url", "coingecko_id",
          "coingecko_logo_url", "name_status", "logo_status", "lunarcrush_sha256",
          "coingecko_sha256", "dhash_distance", "mean_color_distance",
          "reason", "price_status", "identity_status", "contract_status",
          "production_approval", "alert_eligible")


def load_unique(path):
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    ids = [r.get("coin_id") for r in rows]
    if not ids or any(not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("Nonempty unique numeric coin IDs are required")
    if not all(str(x).isdigit() for x in ids):
        raise ValueError("Coin ID must be numeric")
    return {r["coin_id"]: r for r in rows}


def trusted(url):
    try:
        parts = urlsplit(url or "")
        return (parts.scheme == "https" and parts.hostname in HOSTS and
                not parts.username and not parts.password and parts.port is None
                and len(url) <= 2048)
    except (ValueError, TypeError):
        return False


def fingerprint(data):
    if not data or len(data) > 1_000_000:
        raise ValueError("empty or oversized image")
    with Image.open(io.BytesIO(data)) as img:
        if img.width * img.height > 2_000_000 or not img.width or not img.height:
            raise ValueError("image dimensions out of bounds")
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        pixels = list(background.convert("RGB").resize((9, 8)).getdata())
    lum = [int(.299*r + .587*g + .114*b) for r,g,b in pixels]
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = bits << 1 | int(lum[y*9+x] > lum[y*9+x+1])
    means = tuple(sum(p[c] for p in pixels)/72 for c in range(3))
    return hashlib.sha256(data).hexdigest(), bits, means


def compare(url_lc, url_cg, get_image):
    if not url_lc or not url_cg:
        return dict(logo_status="IMAGE_URL_MISSING", reason="A provider URL is absent")
    if not trusted(url_lc) or not trusted(url_cg):
        return dict(logo_status="IMAGE_HOST_UNTRUSTED", reason="Non-allowlisted image URL")
    try:
        sha_l, bits_l, mean_l = fingerprint(get_image(url_lc))
    except Exception as exc:
        return dict(logo_status="LUNARCRUSH_IMAGE_ERROR", reason=type(exc).__name__)
    try:
        sha_g, bits_g, mean_g = fingerprint(get_image(url_cg))
    except Exception as exc:
        return dict(logo_status="COINGECKO_IMAGE_ERROR", reason=type(exc).__name__,
                    lunarcrush_sha256=sha_l)
    diff = (bits_l ^ bits_g).bit_count()
    color = sum((a-b)**2 for a,b in zip(mean_l,mean_g))**0.5
    state = ("EXACT_IMAGE_BYTES" if sha_l == sha_g else
             "POSSIBLE_VISUAL_MATCH" if diff <= 5 and color <= 35 else
             "LOGO_REVIEW_REQUIRED")
    return dict(logo_status=state, lunarcrush_sha256=sha_l,
                coingecko_sha256=sha_g, dhash_distance=diff,
                mean_color_distance=round(color, 2),
                reason="Branding evidence only; not contract or canonical identity proof")


def reconcile(inventory, prior, get_image, expected=20, expected_matches=12):
    if set(inventory) != set(prior) or len(prior) != expected:
        raise ValueError("Identity cohort differs between source artifacts")
    if sum(r.get("name_status") == "EXACT_NORMALIZED_NAME_SYMBOL" for r in prior.values()) != expected_matches:
        raise ValueError("Prior unique CoinGecko match count changed")
    results = []
    for cid, old in prior.items():
        lc = inventory[cid]
        if lc.get("lookup_status") != "FOUND" or lc.get("name_status") != "EXACT_NORMALIZED_NAME_SYMBOL":
            raise ValueError("LC identity was not corroborated in inventory: " + cid)
        if (old.get("lunarcrush_name") != lc.get("name") or
                old.get("symbol") != lc.get("symbol") or
                old.get("price_status") != "PRICE_CONFLICT_REVIEW"):
            raise ValueError("Archived name/symbol/price status mismatch: " + cid)
        result = {k: "" for k in FIELDS}
        result.update(coin_id=cid, symbol=old["symbol"], name=old["lunarcrush_name"],
                      lunarcrush_logo_url=lc.get("lunarcrush_logo_url", ""),
                      coingecko_id=old.get("coingecko_id", ""),
                      coingecko_logo_url=old.get("coingecko_logo_url", ""),
                      name_status=old.get("name_status", ""),
                      price_status=old.get("price_status", ""),
                      identity_status="REVIEW_REQUIRED", contract_status="NOT_VERIFIED",
                      production_approval="NO", alert_eligible="NO")
        if old.get("name_status") != "EXACT_NORMALIZED_NAME_SYMBOL":
            result.update(logo_status="COINGECKO_IDENTITY_UNRESOLVED",
                          reason="No unique CoinGecko full-name and ticker match; compare only after canonical review")
        elif not old.get("coingecko_id"):
            raise ValueError("Unique match lacks CoinGecko ID: " + cid)
        else:
            result.update(compare(result["lunarcrush_logo_url"],
                                  result["coingecko_logo_url"], get_image))
        results.append(result)
    return results


def write(inventory_csv, prior_csv, output, get_image, expected=20, expected_matches=12):
    inventory, prior = load_unique(inventory_csv), load_unique(prior_csv)
    results = reconcile(inventory, prior, get_image, expected, expected_matches)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "lunarcrush_coingecko_logo_comparison.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        writer.writerows(results)
    summary = dict(candidates=len(results), unique_name_matches=expected_matches,
                   statuses=dict(Counter(r["logo_status"] for r in results)),
                   images_compared=sum(r["logo_status"] in
                      {"EXACT_IMAGE_BYTES","POSSIBLE_VISUAL_MATCH","LOGO_REVIEW_REQUIRED"}
                       for r in results),
                   identity_verified=0, production_approvals=0, alerts=0,
                   policy="Research-only; no canonical identity promotion from names or logos")
    (out / "lunarcrush_coingecko_logo_comparison.json").write_text(
        json.dumps(summary, indent=2) + "\n")
    return summary


class ImageClient:
    def __init__(self, cache):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.last = 0.0

    def get(self, url):
        if not trusted(url):
            raise ValueError("Image URL not permitted")
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".img")
        if path.exists() and time.time()-path.stat().st_mtime < 86400:
            return path.read_bytes()
        interval = 1.0-(time.monotonic()-self.last)
        if interval > 0:
            time.sleep(interval)
        for retry in range(3):
            self.last = time.monotonic()
            response = requests.get(url, timeout=15, allow_redirects=False,
                                    stream=True,
                                    headers={"Accept": "image/png,image/jpeg,image/webp"})
            try:
                if response.status_code == 429 and retry < 2:
                    time.sleep(5*(2**retry))
                    continue
                if 300 <= response.status_code < 400:
                    raise ValueError("Image redirected; no automatic redirect following")
                response.raise_for_status()
                if not response.headers.get("Content-Type", "").lower().startswith("image/"):
                    raise ValueError("Non-image content type")
                data = bytearray()
                for block in response.iter_content(65536):
                    data.extend(block)
                    if len(data) > 1_000_000:
                        raise ValueError("Image too large")
                path.write_bytes(data)
                return bytes(data)
            finally:
                response.close()
        raise RuntimeError("Rate limited")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", required=True)
    p.add_argument("--prior", required=True)
    p.add_argument("--output", default="reports/lunarcrush_coingecko_logo_comparison")
    p.add_argument("--cache", default="reports/lunarcrush_coingecko_logo_cache")
    p.add_argument("--expected", type=int, default=20)
    p.add_argument("--expected-matches", type=int, default=12)
    args = p.parse_args()
    if args.expected < 1 or args.expected_matches < 1 or args.expected_matches > args.expected:
        p.error("Invalid expected cohort")
    result = write(args.inventory, args.prior, args.output,
                   ImageClient(args.cache).get, args.expected, args.expected_matches)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
