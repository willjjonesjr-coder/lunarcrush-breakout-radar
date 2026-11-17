#!/usr/bin/env python3
"""Research-only nine-CEX discovery for the *same* ranked historical smoke cohort.

Reuses PR #57 market/candle audit and PR #58 same-run before/after comparison.
Never edits data_price/, approved inventory, symbol_map, production data or alerts.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from tools.audit_expanded_cex_coverage import EXCHANGES
from tools.ccxt_backfill import universe
from tools.compare_cex_coverage import ORIGINAL, ADDED, READY


def make_queue(data_dir, top, radar_csv):
    """Use exactly the backfill cohort/order; no alternative ranked queue."""
    if not 1 <= top <= 80:
        raise ValueError("research cohort must be 1-80")
    ids = universe(data_dir, top)
    with open(radar_csv, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    identity = {}
    for row in rows:
        raw = str(row.get("id") or "").strip()
        try:
            key = str(int(float(raw)))
        except ValueError:
            continue
        identity[key] = row
    queue = []
    for rank, coin_id in enumerate(ids, 1):
        row = identity.get(str(coin_id), {})
        queue.append({
            "review_rank": rank, "coin_id": str(coin_id),
            "symbol": str(row.get("symbol") or "").strip().upper(),
            "name": str(row.get("name") or ""),
            "breakout_score": row.get("breakout_score", ""),
        })
    return queue


def analyze(rows, legacy_rows):
    """Aggregate unique-coin coverage per venue, preserving unavailable/unknown."""
    ids = sorted({str(r.get("coin_id")) for r in rows if r.get("coin_id")})
    per_exchange = []
    venues = list(EXCHANGES)
    for exchange in venues:
        group = [r for r in rows if r.get("exchange") == exchange]
        found = {str(r["coin_id"]) for r in group if r.get("market_status") == "FOUND_PROVISIONAL"}
        three_hundred = {str(r["coin_id"]) for r in group if r.get("history_status") in READY}
        five_hundred = {str(r["coin_id"]) for r in group if r.get("history_status") == "500_BAR_READY_PROVISIONAL"}
        unavailable = {str(r["coin_id"]) for r in group if r.get("market_status") == "EXCHANGE_UNAVAILABLE"}
        errors = {str(r["coin_id"]) for r in group if r.get("history_status") in ("OHLCV_ERROR", "OHLCV_UNSUPPORTED")}
        per_exchange.append({
            "exchange": exchange,
            "cohort_coins": len(ids), "spot_market_coins": len(found),
            "history_300_plus_coins": len(three_hundred),
            "history_500_coins": len(five_hundred),
            "unavailable_coins": len(unavailable), "ohlcv_error_coins": len(errors),
            "identity_status": "UNVERIFIED_RESEARCH_ONLY",
            "production_approvals": 0,
        })
    groups = defaultdict(list)
    for row in rows:
        if row.get("coin_id"):
            groups[str(row["coin_id"])].append(row)
    incremental_300, incremental_500 = set(), set()
    available_300, available_500 = set(), set()
    for coin_id, group in groups.items():
        original = [r for r in group if r.get("exchange") in ORIGINAL]
        added = [r for r in group if r.get("exchange") in ADDED]
        old300 = any(r.get("history_status") in READY for r in original)
        new300 = any(r.get("history_status") in READY for r in added)
        old500 = any(r.get("history_status") == "500_BAR_READY_PROVISIONAL" for r in original)
        new500 = any(r.get("history_status") == "500_BAR_READY_PROVISIONAL" for r in added)
        if old300 or new300:
            available_300.add(coin_id)
        if old500 or new500:
            available_500.add(coin_id)
        if new300 and not old300:
            incremental_300.add(coin_id)
        if new500 and not old500:
            incremental_500.add(coin_id)
    legacy_status = defaultdict(int)
    legacy_exchange = defaultdict(int)
    for row in legacy_rows:
        status = str(row.get("status") or "unknown")
        legacy_status[status] += 1
        if row.get("exchange"):
            legacy_exchange[str(row["exchange"])] += 1
    return per_exchange, {
        "cohort_coins": len(ids),
        "market_venues_attempted": venues,
        "venues_unavailable": [r["exchange"] for r in per_exchange if r["unavailable_coins"]],
        "research_300_plus_unique_coins": len(available_300),
        "research_500_unique_coins": len(available_500),
        "incremental_300_plus_unique_coins_vs_original_three": len(incremental_300),
        "incremental_500_unique_coins_vs_original_three": len(incremental_500),
        "incremental_300_plus_coin_ids": sorted(incremental_300),
        "incremental_500_coin_ids": sorted(incremental_500),
        "legacy_selected_status_counts": dict(legacy_status),
        "legacy_selected_exchange_counts": dict(legacy_exchange),
        "identity_approvals": 0, "production_imports": 0,
        "note": ("Same-cohort nine-venue research discovery, NOT extra verified histories. "
                 "Legacy first-match selections and all production approvals are unchanged. "
                 "Symbol/spot/candle matches are unverified; unavailable venues are unknown, "
                 "not proof of delisting. No research output may be imported automatically."),
    }


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    prepare = subs.add_parser("prepare")
    prepare.add_argument("--top", type=int, default=20)
    prepare.add_argument("--data-dir", default="data")
    prepare.add_argument("--radar", default="reports/breakout_radar.csv")
    prepare.add_argument("--output", default="reports/historical_research_queue.json")
    report = subs.add_parser("report")
    report.add_argument("--coverage", default="reports/expanded_cex_coverage.csv")
    report.add_argument("--inventory", default="reports/backfill_inventory.csv")
    report.add_argument("--output", default="reports/historical_exchange_diversity")
    args = parser.parse_args()
    if args.command == "prepare":
        cohort = make_queue(args.data_dir, args.top, args.radar)
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"first_review_batch": cohort,
                                    "research_only": True}, indent=2) + "\n")
        print(f"Prepared same-cohort nine-CEX research queue: {len(cohort)} coins", flush=True)
    else:
        with open(args.coverage, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        with open(args.inventory, newline="", encoding="utf-8") as f:
            legacy = list(csv.DictReader(f))
        per_exchange, totals = analyze(rows, legacy)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(per_exchange[0]))
            writer.writeheader()
            writer.writerows(per_exchange)
        out.with_suffix(".json").write_text(json.dumps(totals, indent=2) + "\n")
        print(json.dumps(totals, indent=2), flush=True)


if __name__ == "__main__":
    main()
