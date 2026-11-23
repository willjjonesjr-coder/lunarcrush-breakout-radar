#!/usr/bin/env python3
"""Refresh exact previously corroborated spot pairs for current provisional research.

No asset mapping discovery, verified inventory updates, or automated alerts.
Historical ranking is retained whole; only CURRENT_ANALYZED entries are refreshed.
"""
import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from provisional_ema import fetch_history, provisional_technicals

FIELDS = (
    "research_rank", "coin_id", "symbol", "name", "breakout_score",
    "historical_ema_status", "historical_evidence_day", "current_selection_status",
    "refresh_status", "exchange", "pair", "history_bars", "history_last_day",
    "ema50", "ema100", "ema200", "refreshed_technical_status", "reason",
    "identity_warning", "price_corroboration_status",
    "production_eligible", "alert_eligible",
)
SAFE_VENUES = {"kraken", "coinbase", "binance"}


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def unique_rows(rows, field, label):
    result = {}
    for row in rows:
        cid = str(row.get(field) or "").strip()
        if not cid or cid in result:
            raise ValueError("Missing/duplicate " + label + " ID: " + cid)
        result[cid] = row
    return result


def same_asset(a, b):
    return all(not a.get(k) or not b.get(k) or
               str(a[k]).strip().casefold() == str(b[k]).strip().casefold()
               for k in ("name", "symbol"))


def eligible_pair(report_row, rank):
    if not report_row:
        return "NO_ORIGINAL_IDENTITY_EVIDENCE", "", ""
    if not same_asset(rank, report_row):
        return "IDENTITY_CONFLICT", "", ""
    if report_row.get("status") != "PROVISIONAL READY":
        return "ORIGINAL_IDENTITY_NOT_READY", "", ""
    venue = str(report_row.get("exchange") or "").strip().lower()
    pair = str(report_row.get("pair") or "").strip()
    base, sep, quote = pair.partition("/")
    if (venue not in SAFE_VENUES or sep != "/" or
        base.upper() != str(rank.get("symbol") or "").upper() or
        quote.upper() not in {"USD", "USDT"} or
        not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", pair)):
        return "UNSUPPORTED_OR_CONFLICTING_PAIR", "", ""
    return "READY", venue, pair


def refresh(ranking, original_report, current_rows, exchange_factory,
            today=None, bars=300):
    if bars < 300:
        raise ValueError("EMA refresh requires at least 300 completed bars")
    today = today or datetime.now(timezone.utc).date()
    required_day = today - timedelta(days=1)
    current = unique_rows(current_rows, "id", "current production")
    original = unique_rows(original_report.get("assets", []), "coin_id", "provisional")
    ranked = unique_rows(ranking, "coin_id", "ranking")
    results, clients = [], {}
    for cid, rank in ranked.items():
        status = str(rank.get("current_selection_status") or "")
        # Re-evaluate rolling membership using today's production file; the
        # archived ranking's status is not assumed to still be current.
        curr = current.get(cid)
        actual_current = bool(curr and curr.get("history_selection") == "ANALYZED"
                              and same_asset(rank, curr))
        result = {k: "" for k in FIELDS}
        result.update(
            research_rank=rank.get("research_rank", ""), coin_id=cid,
            symbol=rank.get("symbol", ""), name=rank.get("name", ""),
            breakout_score=rank.get("breakout_score", ""),
            historical_ema_status=rank.get("provisional_ema_status", ""),
            historical_evidence_day=rank.get("ema_evidence_day", ""),
            current_selection_status="CURRENT_ANALYZED" if actual_current else
                ("CURRENT_IDENTITY_CONFLICT" if curr and not same_asset(rank, curr)
                 else "OUTSIDE_CURRENT_SELECTION"),
            refresh_status="NOT_EVALUATED", identity_warning="PROVISIONAL — USER DUE DILIGENCE REQUIRED",
            price_corroboration_status=rank.get("price_corroboration_status") or "UNKNOWN",
            production_eligible="NO", alert_eligible="NO")
        if not actual_current:
            result.update(refresh_status="RETAINED_HISTORICAL_ONLY",
                          reason="Not in current analyzed production cohort; no live market fetch")
            results.append(result)
            continue
        if status != "CURRENT_ANALYZED":
            # Older ranking mismatches cannot silently become current without review.
            result.update(refresh_status="REVIEW_CURRENT_SELECTION_CHANGE",
                          reason="Archived research ranking did not mark this ID currently analyzed")
            results.append(result)
            continue
        source = original.get(cid)
        decision, venue, pair = eligible_pair(source, rank)
        if decision != "READY":
            result.update(refresh_status=decision, reason="No safe exact previously corroborated pair")
            results.append(result)
            continue
        result.update(exchange=venue, pair=pair)
        try:
            if venue not in clients:
                clients[venue] = exchange_factory(venue)
                clients[venue].load_markets()
            candles = fetch_history(clients[venue], pair, required_day, bars)
            if len(candles) < bars or str(candles[-1][0])[:10] != required_day.isoformat():
                raise ValueError("History not contiguous through latest complete UTC day")
            tech = provisional_technicals(candles)
            result.update(
                refresh_status="REFRESHED_PROVISIONAL",
                history_bars=len(candles), history_last_day=required_day.isoformat(),
                refreshed_technical_status=tech["provisional_technical_status"],
                ema50=tech["provisional_ema50"],
                ema100=tech["provisional_ema100"],
                ema200=tech["provisional_ema200"],
                reason="EMA from exact spot pair; old identity evidence not re-verified")
        except Exception as exc:
            result.update(refresh_status="REFRESH_FAILED",
                          reason=(type(exc).__name__ + ": " + str(exc))[:450])
        results.append(result)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "required_completed_day": required_day.isoformat(),
        "cohort_size": len(results),
        "current_candidates": sum(x["current_selection_status"] == "CURRENT_ANALYZED" for x in results),
        "refreshed": sum(x["refresh_status"] == "REFRESHED_PROVISIONAL" for x in results),
        "refreshed_aligned": sum(x["refreshed_technical_status"] == "PROVISIONAL EMA ALIGNED" for x in results),
        "status_counts": dict(sorted(Counter(x["refresh_status"] for x in results).items())),
        "historical_retained": sum(x["refresh_status"] == "RETAINED_HISTORICAL_ONLY" for x in results),
        "production_promotions": 0, "alerts": 0,
        "policy": "Research only; price-series refresh is NOT fresh canonical identity or cross-source corroboration.",
    }
    return results, summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ranking", required=True)
    p.add_argument("--provisional-report", required=True)
    p.add_argument("--current-production", default="reports/breakout_radar.csv")
    p.add_argument("--output", default="reports/provisional_ema_refresh")
    p.add_argument("--bars", type=int, default=300)
    args = p.parse_args()
    import ccxt
    original = json.loads(Path(args.provisional_report).read_text(encoding="utf-8"))
    if not isinstance(original, dict) or not isinstance(original.get("assets"), list):
        p.error("Expected original provisional research report.json")
    if not (original.get("required_completed_day") and original.get("as_of")):
        p.error("Original provisional report missing provenance")
    def factory(venue):
        return getattr(ccxt, venue)({"enableRateLimit": True, "timeout": 30000})
    rows, summary = refresh(read_csv(args.ranking), original,
                            read_csv(args.current_production), factory, bars=args.bars)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "refreshed_ranking.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
