"""Name-and-symbol corroborated exchange histories for research, never verified inventory.

All joins use a unique LunarCrush ID and a unique normalized name AND symbol.
Missing contract documentation is a review flag, not an automatic rejection.
"""
import argparse
import csv
import json
import math
import re
import time
import unicodedata
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from phase2_safeguards import ema
from tools.ema_identity_evidence import fetch

API = "https://api.coingecko.com/api/v3"
# CoinGecko market identifiers, not display names or inferred ticker aliases.
EXCHANGES = {"kraken": "kraken", "coinbase": "gdax", "binance": "binance"}
QUOTES = ("USD", "USDT")
FIELDS = ("time", "open", "high", "low", "close", "volume", "exchange", "pair")


def normalized(value):
    """Conservative normalization: Unicode, case and whitespace only (no aliases)."""
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def identity_key(row):
    return normalized(row.get("name")), normalized(row.get("symbol"))


def contracts(row):
    platforms = row.get("platforms") or {}
    if isinstance(platforms, str):
        platforms = json.loads(platforms)
    if not isinstance(platforms, dict):
        raise ValueError("Malformed contract evidence")
    result = {normalized(k): str(v).strip() for k, v in platforms.items() if k and v}
    if row.get("network") and row.get("contract_address"):
        result[normalized(row["network"])] = str(row["contract_address"]).strip()
    return result


def contract_conflict(left, right):
    # Chain-specific address formats are case sensitive except EVM hex addresses.
    def address(v):
        return v.lower() if re.fullmatch(r"0x[0-9a-fA-F]{40}", v) else v
    return any(address(left[k]) != address(right[k]) for k in left.keys() & right.keys())


def match_identities(universe, catalog, registry=None):
    """Require uniqueness across BOTH complete input snapshots, before selection."""
    registry = registry or {}
    lc_keys, cg_keys, lc_ids, cg_ids = (defaultdict(list) for _ in range(4))
    for row in universe:
        lc_keys[identity_key(row)].append(row)
        lc_ids[str(row.get("id", ""))].append(row)
    for row in catalog:
        cg_keys[identity_key(row)].append(row)
        cg_ids[str(row.get("id", ""))].append(row)
    output = {}
    for cid, rows in lc_ids.items():
        row = rows[0]
        key = identity_key(row)
        candidates = cg_keys[key]
        item = dict(coin_id=cid, name=row.get("name", ""), symbol=row.get("symbol", ""),
                    status="REVIEW REQUIRED", reason="", coingecko_id="", review_flags=[],
                    eligible_for_verified_inventory=False, eligible_for_alerts=False)
        if not re.fullmatch(r"[0-9]+", cid) or not all(key):
            item["reason"] = "Missing or invalid LunarCrush ID/name/symbol"
        elif len(rows) != 1 or len(lc_keys[key]) != 1:
            item["reason"] = "Ambiguous LunarCrush ID or normalized name/symbol"
        elif len(candidates) != 1 or len(cg_ids[str(candidates[0].get('id', ''))]) != 1:
            item["reason"] = "No unique CoinGecko name AND symbol match"
        else:
            candidate = candidates[0]
            cg_id = candidate.get("id")
            approved = registry.get(cid, {})
            if not isinstance(approved, dict):
                item["reason"] = "Malformed registry evidence; review required"
                output[cid] = item
                continue
            expected = approved.get("canonical_id") or approved.get("coingecko_id")
            lc_cg = row.get("coingecko_id")
            try:
                for evidence in (row, candidate, approved):
                    contracts(evidence)
            except (ValueError, TypeError, AttributeError):
                item["reason"] = "Malformed contract evidence; review required"
                output[cid] = item
                continue
            if not isinstance(cg_id, str) or not cg_id.strip():
                item["reason"] = "Missing CoinGecko ID"
            elif (expected and expected != cg_id) or (lc_cg and lc_cg != cg_id):
                item["reason"] = "Conflicting existing canonical identity"
            elif (contract_conflict(contracts(row), contracts(candidate))
                  or contract_conflict(contracts(approved), contracts(candidate))
                  or contract_conflict(contracts(row), contracts(approved))):
                item["reason"] = "Conflicting contract evidence"
            else:
                item.update(status="MATCHED PROVISIONALLY", coingecko_id=cg_id,
                            platforms={**contracts(row), **contracts(approved), **contracts(candidate)}, reason="Exchange listing not yet corroborated")
                item["review_flags"] = ["Identity due diligence pending"]
                if not contracts(row) or not contracts(candidate):
                    item["review_flags"].append("Missing contract/native-chain documentation")
        output[cid] = item
    return output


def corroborated_pairs(identity, details, tickers):
    """Only exact provider market ID/base/quote and canonical asset evidence."""
    if details.get("id") != identity["coingecko_id"] or identity_key(details) != identity_key(identity):
        raise ValueError("CoinGecko detail identity conflicts with catalog")
    if contract_conflict(identity.get("platforms", {}), contracts(details)):
        raise ValueError("CoinGecko contract evidence changed")
    pairs = []
    for exchange, market_id in EXCHANGES.items():
        for quote in QUOTES:
            matches = [t for t in tickers if t.get("market", {}).get("identifier") == market_id
                       and normalized(t.get("base")) == normalized(identity["symbol"])
                       and normalized(t.get("target")) == normalized(quote)]
            if any(t.get("coin_id") and t["coin_id"] != identity["coingecko_id"] for t in matches):
                raise ValueError("Exchange listing has conflicting CoinGecko asset ID")
            if any(t.get("is_stale") is not True and t.get("is_anomaly") is not True for t in matches):
                pairs.append((exchange, str(identity["symbol"]).strip().upper() + "/" + quote))
    return pairs


def validate_candles(candles, required_day, bars=300):
    """Reject malformed, duplicate-conflicting, misaligned or incomplete daily data."""
    if bars < 300:
        raise ValueError("At least 300 bars required for EMA research")
    days = {}
    for candle in candles:
        if len(candle) < 6:
            raise ValueError("Malformed candle")
        stamp = float(candle[0])
        if not math.isfinite(stamp) or stamp % 86400000:
            raise ValueError("Non-UTC daily candle timestamp")
        day = datetime.fromtimestamp(stamp / 1000, timezone.utc).date()
        # Exchanges commonly include today's open candle. Never use it.
        if day == required_day + timedelta(days=1):
            continue
        if day > required_day:
            raise ValueError("Future candle")
        vals = [float(v) for v in candle[1:6]]
        o, h, l, c, volume = vals
        if (not all(math.isfinite(v) for v in vals) or min(vals[:4]) <= 0 or volume < 0
                or h < max(o, c, l) or l > min(o, c, h)):
            raise ValueError("Invalid OHLCV envelope")
        if day in days and days[day] != vals:
            raise ValueError("Conflicting duplicate candle")
        days[day] = vals
    selected = sorted(days)[-bars:]
    if len(selected) < bars or selected[-1] != required_day:
        raise ValueError("Insufficient history or latest completed candle missing")
    if any((b - a).days != 1 for a, b in zip(selected, selected[1:])):
        raise ValueError("Daily candle gaps")
    return [[d.isoformat() + "T00:00:00Z", *days[d]] for d in selected]


def provisional_technicals(rows):
    prices = [r[4] for r in rows[-300:]]
    e50, e100, e200 = [ema(prices, n) for n in (50, 100, 200)]
    meets = (e50[-1] > e100[-1] > e200[-1] and e50[-1] > e50[-6]
             and e50[-1] * .97 <= prices[-1] <= e50[-1] * 1.10)
    return {"provisional_technical_status": "PROVISIONAL EMA " + ("ALIGNED" if meets else "NOT ALIGNED"),
            **{f"provisional_ema{n}": round(v[-1], 10) for n, v in ((50, e50), (100, e100), (200, e200))}}


def fetch_history(client, pair, required_day, bars):
    market = client.markets.get(pair, {})
    base, quote = pair.split("/")
    if (not client.has.get("fetchOHLCV") or market.get("spot") is not True
            or market.get("active") is not True or market.get("base") != base or market.get("quote") != quote):
        raise ValueError("Exact active spot pair unavailable")
    since = int(datetime.combine(required_day - timedelta(days=bars + 10),
                                 datetime.min.time(), timezone.utc).timestamp() * 1000)
    candles = []
    for _ in range(20):
        chunk = client.fetch_ohlcv(pair, "1d", since=since, limit=min(720, bars + 15))
        if not chunk:
            break
        candles.extend(chunk)  # Preserve duplicates for integrity validation.
        following = max(int(c[0]) for c in chunk) + 86400000
        if following <= since:
            break
        since = following
        if datetime.fromtimestamp(since / 1000, timezone.utc).date() > required_day:
            break
    return validate_candles(candles, required_day, bars)


def build(universe, targets, catalog, detail_fetch, ticker_fetch, exchange_factory,
          output_dir, today=None, bars=300, registry=None):
    """Generate separate report and histories. No verified file is read as a fallback."""
    if bars < 300:
        raise ValueError("At least 300 bars required for EMA research")
    today = today or datetime.now(timezone.utc).date()
    required = today - timedelta(days=1)
    output_dir = Path(output_dir)
    # A dedicated subtree prevents accidental overwriting of verified histories.
    if output_dir.name != "provisional_ema":
        raise ValueError("Output directory must be named provisional_ema")
    output_dir.mkdir(parents=True, exist_ok=True)
    clients, results = {}, []
    def checkpoint():
        report = dict(as_of=today.isoformat(), required_completed_day=required.isoformat(),
                      policy="Provisional research only. Not verified inventory, scoring, confirmation or alerts.",
                      counts=dict(Counter(x["status"] for x in results)), assets=results)
        temporary = output_dir / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        temporary.replace(output_dir / "report.json")
        return report
    checkpoint()  # Invalidate earlier reports even if this run is interrupted.
    matches = match_identities(universe, catalog, registry)
    counts = Counter(str(r.get("id", "")) for r in targets)
    for target in targets:
        cid = str(target.get("id", ""))
        item = dict(matches.get(cid, dict(coin_id=cid, status="REVIEW REQUIRED",
                                        reason="Missing from LunarCrush universe")))
        item.update(provisional_technical_status="NOT EVALUATED", provisional_ema50=None,
                    provisional_ema100=None, provisional_ema200=None,
                    eligible_for_alerts=False, eligible_for_verified_inventory=False)
        try:
            target_contracts = contracts(target)
        except (ValueError, TypeError, AttributeError):
            target_contracts = {}
            item.update(status="REVIEW REQUIRED", reason="Malformed target contract evidence")
        if (counts[cid] != 1 or identity_key(target) != identity_key(item)
                or (target.get("coingecko_id") and target["coingecko_id"] != item.get("coingecko_id"))
                or contract_conflict(target_contracts, item.get("platforms", {}))):
            item.update(status="REVIEW REQUIRED", reason="Conflicting target/universe identity")
        if item["status"] == "MATCHED PROVISIONALLY":
            item["platforms"] = {**item.get("platforms", {}), **target_contracts}
            try:
                details = detail_fetch(item["coingecko_id"])
                pairs = corroborated_pairs(item, details, ticker_fetch(item["coingecko_id"]))
                if not contracts(details) and "Missing contract/native-chain documentation" not in item["review_flags"]:
                    item["review_flags"].append("Missing contract/native-chain documentation")
                if not pairs:
                    raise ValueError("No corroborated exchange/pair in returned CoinGecko listings")
                item["listing_evidence_url"] = API + "/coins/" + urllib.parse.quote(item["coingecko_id"], safe="") + "/tickers"
                item["evidence_checked_on"] = today.isoformat()
                errors = []
                for exchange, pair in pairs:
                    try:
                        if exchange not in clients:
                            clients[exchange] = exchange_factory(exchange)
                            clients[exchange].load_markets()
                        rows = fetch_history(clients[exchange], pair, required, bars)
                        filename = cid + ".csv"
                        with (output_dir / filename).open("w", newline="") as f:
                            writer = csv.writer(f)
                            writer.writerow(FIELDS)
                            writer.writerows([*r, exchange, pair] for r in rows)
                        item.update(status="PROVISIONAL READY", reason="User identity review pending",
                                    exchange=exchange, pair=pair, bars=len(rows), latest_day=required.isoformat(),
                                    history_file=filename, **provisional_technicals(rows))
                        break
                    except Exception as exc:
                        errors.append(f"{exchange} {pair}: {type(exc).__name__}: {exc}")
                if item["status"] != "PROVISIONAL READY":
                    item.update(status="HISTORY UNAVAILABLE", reason="; ".join(errors)[:1000])
            except Exception as exc:
                item.update(status="REVIEW REQUIRED", reason=f"{type(exc).__name__}: {exc}"[:1000])
        # An earlier success must never survive a current failed identity/history check.
        if item["status"] != "PROVISIONAL READY" and re.fullmatch(r"[0-9]+", cid):
            (output_dir / (cid + ".csv")).unlink(missing_ok=True)
        results.append(item)
        checkpoint()
    return checkpoint()


def report_fields(path, today=None):
    """Expose only fresh, uniquely keyed research fields for the sortable report."""
    today = today or datetime.now(timezone.utc).date()
    if not Path(path).exists():
        return {}
    try:
        report = json.loads(Path(path).read_text())
        if not isinstance(report, dict) or not isinstance(report.get("assets"), list):
            return {}
        rows = report["assets"]
        if any(not isinstance(r, dict) for r in rows):
            return {}
    except (OSError, ValueError):
        return {}  # Optional research must not break the existing verified report.
    counts = Counter(str(r.get("coin_id", "")) for r in rows)
    current = (report.get("as_of") == today.isoformat() and
               report.get("required_completed_day") == (today - timedelta(days=1)).isoformat())
    output = {}
    for row in rows:
        cid = str(row.get("coin_id", ""))
        if counts[cid] != 1:
            continue
        ready = (current and row.get("status") == "PROVISIONAL READY" and
                 row.get("latest_day") == report["required_completed_day"])
        output[cid] = {
            "name": row.get("name"), "symbol": row.get("symbol"),
            "provisional_status": row.get("status") if current else "STALE PROVISIONAL REPORT",
            "provisional_technical_status": row.get("provisional_technical_status") if ready else "NOT EVALUATED",
            "provisional_review_flags": "; ".join(row.get("review_flags", [])),
            "provisional_reason": row.get("reason", "") if current else "Rerun provisional research for current candles and identity evidence",
            "provisional_exchange_pair": (row.get("exchange", "") + " " + row.get("pair", "")).strip(),
            **{f"provisional_ema{n}": row.get(f"provisional_ema{n}") if ready else None for n in (50, 100, 200)},
        }
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--universe", default="data/universe_latest.csv")
    p.add_argument("--targets", default="reports/breakout_radar.csv")
    p.add_argument("--output", default="reports/provisional_ema")
    p.add_argument("--bars", type=int, default=300)
    p.add_argument("--delay", type=float, default=6, help="Seconds between CoinGecko requests")
    a = p.parse_args()
    import ccxt
    def request(url):
        time.sleep(max(0, a.delay))
        return fetch(url)
    def details(cid):
        return request(API + "/coins/" + urllib.parse.quote(cid, safe="") +
                       "?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false")
    def tickers(cid):
        found = []
        for page in range(1, 6):
            rows = request(API + "/coins/" + urllib.parse.quote(cid, safe="") +
                           "/tickers?page=" + str(page)).get("tickers", [])
            found.extend(rows)
            if len(rows) < 100:
                break
        return found  # Missing/beyond bounded pages is withheld, never guessed.
    with Path(a.universe).open(newline="") as f:
        universe = list(csv.DictReader(f))
    with Path(a.targets).open(newline="") as f:
        targets = list(csv.DictReader(f))
    registry = json.loads(Path("config/asset_identity_registry.json").read_text())
    report = build(universe, targets, request(API + "/coins/list?include_platform=true"), details, tickers,
                   lambda name: getattr(ccxt, name)({"enableRateLimit": True, "timeout": 30000}),
                   Path(a.output), bars=a.bars, registry=registry)
    print(json.dumps(report["counts"]))


if __name__ == "__main__":
    main()
