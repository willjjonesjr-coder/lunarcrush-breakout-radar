#!/usr/bin/env python3
"""Compare same-run spot-market/price-history discovery: original 3 CEXs vs expanded 9.

Research only. No candidate becomes approved based on exchange symbol matching.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

ORIGINAL = ("kraken", "coinbase", "binance")
ADDED = ("okx", "bybit", "bitget", "gate", "mexc", "kucoin")
READY = {"300_BAR_READY_PROVISIONAL", "500_BAR_READY_PROVISIONAL"}
COLUMNS = ("coin_id", "symbol", "name", "original_market_found", "new_market_found",
           "incremental_market_discovery", "original_300_bar_found", "new_300_bar_found",
           "incremental_300_bar_discovery", "original_exchanges_unavailable",
           "new_exchanges_unavailable", "new_markets", "new_300_bar_sources",
           "identity_status", "recommendation")


def metrics(group, venues):
    rows = [r for r in group if r.get("exchange") in venues]
    markets = [r for r in rows if r.get("market_status") == "FOUND_PROVISIONAL"]
    good = [r for r in rows if r.get("history_status") in READY]
    unavailable = sorted({r["exchange"] for r in rows if r.get("market_status") == "EXCHANGE_UNAVAILABLE"})
    return {"market": bool(markets), "ready": bool(good),
            "unavailable": unavailable,
            "markets": sorted({r["exchange"] + ":" + r.get("pair", "") for r in markets}),
            "ready_sources": sorted({r["exchange"] + ":" + r.get("pair", "") for r in good})}


def compare(rows):
    groups = defaultdict(list)
    for r in rows:
        if r.get("coin_id"):
            groups[str(r["coin_id"])].append(r)
    findings = []
    for cid in sorted(groups, key=lambda v: (int(v) if v.isdigit() else 10**20, v)):
        group = groups[cid]
        old = metrics(group, ORIGINAL)
        new = metrics(group, ADDED)
        incremental_market = new["market"] and not old["market"]
        incremental_ready = new["ready"] and not old["ready"]
        if old["unavailable"]:
            note = "ORIGINAL_EXCHANGE_UNAVAILABLE_REVIEW"
        elif incremental_ready:
            note = "REVIEW_NEW_300_BAR_SOURCE_IDENTITY_AND_LIQUIDITY"
        elif incremental_market:
            note = "REVIEW_NEW_MARKET_IDENTITY_AND_HISTORY"
        elif new["market"] or old["market"]:
            note = "EXISTING_MARKET_OR_INSUFFICIENT_HISTORY"
        else:
            note = "NO_OBSERVED_SPOT_MARKET"
        findings.append({
            "coin_id": cid, "symbol": group[0].get("symbol", ""),
            "name": group[0].get("name", ""),
            "original_market_found": old["market"],
            "new_market_found": new["market"],
            "incremental_market_discovery": incremental_market,
            "original_300_bar_found": old["ready"],
            "new_300_bar_found": new["ready"],
            "incremental_300_bar_discovery": incremental_ready,
            "original_exchanges_unavailable": ";".join(old["unavailable"]),
            "new_exchanges_unavailable": ";".join(new["unavailable"]),
            "new_markets": ";".join(new["markets"]),
            "new_300_bar_sources": ";".join(new["ready_sources"]),
            "identity_status": "UNVERIFIED_RESEARCH_ONLY",
            "recommendation": note,
        })
    return findings


def summary(findings, rows):
    def n(key): return sum(bool(r[key]) for r in findings)
    attempted = {r.get("exchange") for r in rows if r.get("exchange")}
    failures = {r.get("exchange") for r in rows if r.get("market_status") == "EXCHANGE_UNAVAILABLE"}
    return {"coins_compared": len(findings),
            "original_three": list(ORIGINAL), "additional_six": list(ADDED),
            "original_market_found": n("original_market_found"),
            "additional_market_found": n("new_market_found"),
            "incremental_market_discovery": n("incremental_market_discovery"),
            "original_300_bar_found": n("original_300_bar_found"),
            "additional_300_bar_found": n("new_300_bar_found"),
            "incremental_300_bar_discovery": n("incremental_300_bar_discovery"),
            "exchange_checks_missing": sorted((set(ORIGINAL + ADDED) - attempted)),
            "exchange_checks_unavailable": sorted(failures),
            "identity_approvals": 0, "production_imports": 0,
            "note": "Within-run discovery comparison only. Missing/unavailable venue is not proof of no listing; matching spot tickers and OHLCV are NOT identity approvals."}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="reports/expanded_cex_coverage.csv")
    p.add_argument("--output", default="reports/expanded_cex_before_after")
    a = p.parse_args()
    with open(a.input, newline="") as f:
        rows = list(csv.DictReader(f))
    findings = compare(rows)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix(".csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(findings)
    report = summary(findings, rows)
    out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
