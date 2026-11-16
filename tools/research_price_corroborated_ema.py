#!/usr/bin/env python3
"""Research-only cross-source price corroboration and provisional EMA for new CEX coins.

No production symbol_map, data_price, approved inventory, scoring or alerts are touched.
A matching price series supports price-corroborated research, not verified asset identity.
"""
import argparse
import csv
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from provisional_ema import fetch_history, provisional_technicals

ALLOWED_EXCHANGES = ("okx", "bybit", "bitget", "gate", "mexc", "kucoin")
ALLOWED_QUOTES = {"USD", "USDT", "USDC"}
FIELDS = ("coin_id", "symbol", "name", "coingecko_id", "exchange", "pair",
          "quote", "reference_source", "reference_last_day", "reference_prices",
          "exchange_prices", "comparison_days", "daily_difference_pct",
          "max_difference_pct", "mean_difference_pct", "tolerance_pct",
          "identity_confidence", "reason", "ema_status", "ema50", "ema100", "ema200",
          "history_bars", "history_last_day", "provenance", "production_approval",
          "alert_eligible", "research_csv")


def load_rows(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def parse_day(value):
    return date.fromisoformat(str(value)[:10])


def reference_history(path, coin_id):
    """Read LunarCrush historical close with exact UTC date key; reject contradictions."""
    result = {}
    for row in load_rows(path):
        raw = str(row.get("time", "")).strip()
        try:
            day = parse_day(raw)
            price = float(row.get("close", ""))
            if not math.isfinite(price) or price <= 0:
                continue
            if row.get("coin_id") and str(row["coin_id"]).strip() != str(coin_id):
                raise ValueError("LunarCrush coin ID conflicts with requested candidate")
            if day in result and result[day] != price:
                raise ValueError("conflicting LunarCrush closes for same UTC day")
            result[day] = price
        except (TypeError, ValueError) as exc:
            if "conflict" in str(exc):
                raise
            continue
    return result


def evaluate_prices(reference, exchange, required_day, tolerance_pct=2.0,
                    minimum_days=3, window=5):
    """Use exact UTC-day overlap ending on required_day; no nearest-time matching."""
    if not 0 < tolerance_pct <= 10 or minimum_days < 3 or window < minimum_days:
        raise ValueError("invalid corroboration policy")
    normalized = {}
    for raw, price in exchange.items():
        day = parse_day(raw)
        value = float(price)
        if not math.isfinite(value) or value <= 0:
            return {"status": "INVALID_EXCHANGE_PRICE", "reason": str(day)}
        if day in normalized and normalized[day] != value:
            return {"status": "CONFLICT", "reason": "conflicting exchange close"}
        normalized[day] = value
    if required_day not in reference or required_day not in normalized:
        return {"status": "INSUFFICIENT_ALIGNED_DATA", "reason": "latest completed UTC day missing"}
    days = [required_day - timedelta(days=i) for i in range(window - 1, -1, -1)]
    aligned = [(d, reference[d], normalized[d]) for d in days if d in reference and d in normalized]
    # Require consecutive aligned dates through latest completed day.
    suffix = []
    for d in reversed(days):
        if d not in reference or d not in normalized:
            break
        suffix.append((d, reference[d], normalized[d]))
    aligned = list(reversed(suffix))
    if len(aligned) < minimum_days:
        return {"status": "INSUFFICIENT_ALIGNED_DATA",
                "reason": f"only {len(aligned)} consecutive aligned UTC dates"}
    checks = []
    for d, ref, src in aligned:
        if not all(math.isfinite(v) and v > 0 for v in (ref, src)):
            return {"status": "INVALID_REFERENCE_PRICE", "reason": str(d)}
        checks.append({"day": d.isoformat(), "reference": ref, "exchange": src,
                       "difference_pct": 100 * abs(src - ref) / ref})
    max_pct = max(r["difference_pct"] for r in checks)
    mean_pct = sum(r["difference_pct"] for r in checks) / len(checks)
    if max_pct > tolerance_pct:
        status, reason = "PRICE_MISMATCH", "at least one aligned day exceeds tolerance"
    else:
        ref_changes = [abs(aligned[i][1] / aligned[i-1][1] - 1) for i in range(1, len(aligned))]
        ex_changes = [abs(aligned[i][2] / aligned[i-1][2] - 1) for i in range(1, len(aligned))]
        if max(ref_changes + ex_changes) < 0.0002:
            status, reason = "LOW_INFORMATION", "both series nearly flat; possible stale prices"
        else:
            status, reason = "PRICE_CORROBORATED", "all aligned daily closes within tolerance"
    return {"status": status, "reason": reason, "checks": checks,
            "max_pct": max_pct, "mean_pct": mean_pct}


def parse_sources(row):
    found = []
    for pair in str(row.get("source_markets") or "").split(";"):
        if not pair:
            continue
        venue, sep, market = pair.partition(":")
        if (not sep or venue not in ALLOWED_EXCHANGES or "/" not in market
                or ":" in market):
            continue
        base, quote = market.split("/", 1)
        if base.upper() != str(row["symbol"]).upper() or quote.upper() not in ALLOWED_QUOTES:
            continue
        found.append((venue, market))
    return list(dict.fromkeys(found))


def known_conflict(entry, conflicts):
    conflict = conflicts.get(str(entry["coin_id"]))
    if conflict:
        return str(conflict) if isinstance(conflict, str) else json.dumps(conflict, sort_keys=True)
    return ""


def write_report(input_csv, archive, output, conflicts=None, today=None, maximum_sources=1,
                 tolerance_pct=2.0, minimum_days=3):
    import ccxt
    today = today or datetime.now(timezone.utc).date()
    required = today - timedelta(days=1)
    conflicts = conflicts or {}
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    price_dir = out / "provisional_ema"
    price_dir.mkdir(exist_ok=True)
    clients = {}
    rows, results = load_rows(input_csv), []
    for item in rows:
        cid = str(item["coin_id"]).strip()
        sym = item.get("symbol", "")
        src_path = Path(archive) / ("history_" + cid + ".csv")
        result = dict.fromkeys(FIELDS, "")
        result.update(coin_id=cid, symbol=sym, name=item.get("name", ""),
                      tolerance_pct=str(tolerance_pct),
                      reference_source="LUNARCRUSH_HISTORY_UTC_DAILY_CLOSE",
                      identity_confidence="PROVISIONAL", ema_status="NOT_EVALUATED",
                      production_approval="NO", alert_eligible="NO",
                      provenance="Exchange CCXT spot OHLCV versus LunarCrush archived close")
        conflict = known_conflict(item, conflicts)
        sources = parse_sources(item)
        if conflict:
            result.update(identity_confidence="CONFLICT", reason=conflict)
        elif not src_path.exists():
            result.update(reason="LunarCrush historical file missing")
        elif not sources:
            result.update(reason="No supported exact-base source pair")
        else:
            try:
                refs = reference_history(src_path, cid)
            except ValueError as exc:
                refs = {}
                result.update(identity_confidence="CONFLICT", reason=str(exc))
            if result["identity_confidence"] != "CONFLICT":
                first_issue = ""
                for exchange, pair in sources[:maximum_sources]:
                    result.update(exchange=exchange, pair=pair, quote=pair.split("/")[1])
                    if exchange not in clients:
                        try:
                            client = getattr(ccxt, exchange)({"enableRateLimit": True, "timeout": 30000})
                            client.load_markets()
                            clients[exchange] = client
                        except Exception as exc:
                            clients[exchange] = exc
                    client = clients[exchange]
                    if isinstance(client, Exception):
                        first_issue = "EXCHANGE_UNAVAILABLE: " + str(client)[:140]
                        continue
                    try:
                        candles = fetch_history(client, pair, required, 500)
                        candle_map = {parse_day(c[0]): float(c[4]) for c in candles}
                        check = evaluate_prices(refs, candle_map, required, tolerance_pct, minimum_days)
                        result.update(identity_confidence=check["status"], reason=check["reason"],
                                      reference_last_day=required.isoformat(),
                                      history_last_day=parse_day(candles[-1][0]).isoformat(),
                                      history_bars=len(candles))
                        if "checks" in check:
                            days = check["checks"]
                            result.update(comparison_days=";".join(c["day"] for c in days),
                                reference_prices=json.dumps([c["reference"] for c in days]),
                                exchange_prices=json.dumps([c["exchange"] for c in days]),
                                daily_difference_pct=json.dumps([round(c["difference_pct"], 6) for c in days]),
                                max_difference_pct=f'{check["max_pct"]:.6f}',
                                mean_difference_pct=f'{check["mean_pct"]:.6f}')
                        if check["status"] == "PRICE_CORROBORATED":
                            technicals = provisional_technicals(candles)
                            csv_path = price_dir / (cid + ".csv")
                            with csv_path.open("w", newline="") as f:
                                w = csv.writer(f)
                                w.writerow(("time", "open", "high", "low", "close", "volume", "exchange", "pair"))
                                w.writerows([*c, exchange, pair] for c in candles)
                            result.update(ema_status=technicals["provisional_technical_status"],
                                ema50=technicals["provisional_ema50"],
                                ema100=technicals["provisional_ema100"],
                                ema200=technicals["provisional_ema200"],
                                research_csv=str(csv_path),
                                reason=check["reason"] + "; PRICE ONLY, identity unverified"
                                + ("; USDT/USDC parity assumed" if result["quote"] != "USD" else ""))
                            break
                        if check["status"] in ("PRICE_MISMATCH", "CONFLICT", "INVALID_EXCHANGE_PRICE", "INVALID_REFERENCE_PRICE"):
                            break  # never search for a market that happens to agree after a hard conflict
                        first_issue = check["reason"]
                    except Exception as exc:
                        first_issue = type(exc).__name__ + ": " + str(exc)[:160]
                if result["identity_confidence"] == "PROVISIONAL":
                    result["reason"] = first_issue or result["reason"] or "No suitable market"
        results.append(result)
    with (out / "price_corroboration.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)
    summary = {"candidates": len(rows), "corroborated": sum(x["identity_confidence"] == "PRICE_CORROBORATED" for x in results),
        "mismatched": sum(x["identity_confidence"] == "PRICE_MISMATCH" for x in results),
        "conflicts": sum(x["identity_confidence"] == "CONFLICT" for x in results),
        "research_ema": sum(x["ema_status"].startswith("PROVISIONAL EMA") for x in results),
        "fully_verified": 0, "production_approvals": 0, "alerts": 0,
        "minimum_aligned_days": minimum_days, "tolerance_pct": tolerance_pct,
        "policy": "Price agreement is corroboration, not canonical identity proof. Research-only EMA output; no production imports."}
    (out / "price_corroboration.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="Incremental identity-readiness CSV")
    p.add_argument("--history-dir", default="data")
    p.add_argument("--output", default="reports/price_corroboration_research")
    p.add_argument("--conflicts", default="config/price_corroboration_conflicts.json")
    p.add_argument("--max-sources", type=int, default=1)
    p.add_argument("--tolerance-pct", type=float, default=2.0)
    p.add_argument("--minimum-days", type=int, default=3)
    a = p.parse_args()
    if not 1 <= a.max_sources <= 3 or not 0 < a.tolerance_pct <= 10 or a.minimum_days < 3:
        p.error("invalid sources, tolerance or minimum day policy")
    conflicts = json.loads(Path(a.conflicts).read_text())
    summary = write_report(a.input, a.history_dir, a.output, conflicts,
                           maximum_sources=a.max_sources, tolerance_pct=a.tolerance_pct,
                           minimum_days=a.minimum_days)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
