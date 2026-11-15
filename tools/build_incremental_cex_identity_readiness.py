"""Research-only identity/import-readiness report for incremental CEX historical sources."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

READY = {"300_BAR_READY_PROVISIONAL", "500_BAR_READY_PROVISIONAL"}
FIELDS = ["priority_rank","coin_id","symbol","name","radar_score","incremental_300_bar",
          "candidate_sources","source_count","source_markets","candles_min","candles_max",
          "latest_day","price_source_state","identity_state","identity_evidence_needed",
          "exchange_evidence_needed","liquidity_evidence_needed","cross_venue_price_check",
          "production_approval","recommended_action"]


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def report(before, coverage):
    groups = defaultdict(list)
    for r in coverage:
        groups[r.get("coin_id", "")].append(r)
    result = []
    for entry in before:
        if entry.get("incremental_300_bar_discovery", "").lower() != "true":
            continue
        cid = entry["coin_id"]
        matches = [r for r in groups[cid] if r.get("history_status") in READY
                   and r.get("exchange") not in ("kraken", "coinbase", "binance")]
        if not matches:
            raise ValueError(f"incremental ready flag with no supporting source: {cid}")
        matches.sort(key=lambda r: (-int(r.get("bars_available") or 0), r["exchange"], r["pair"]))
        sources = sorted({r["exchange"] for r in matches})
        bars = [int(r["bars_available"]) for r in matches]
        score = next((r.get("breakout_score", "") for r in groups[cid] if r.get("breakout_score")), "")
        result.append(dict(coin_id=cid, symbol=entry.get("symbol", ""), name=entry.get("name", ""),
            radar_score=score, incremental_300_bar="YES", candidate_sources=";".join(sources),
            source_count=len(sources), source_markets=";".join(sorted({r["exchange"] + ":" + r["pair"] for r in matches})),
            candles_min=min(bars), candles_max=max(bars),
            latest_day=max(r.get("latest_day", "") for r in matches),
            price_source_state="PROVISIONAL_TICKER_MATCH_ONLY", identity_state="UNVERIFIED",
            identity_evidence_needed="LunarCrush coin ID + independent canonical ID + official contract/native chain",
            exchange_evidence_needed="Official exchange asset ID, network/contract and independent confirmation of canonical base asset",
            liquidity_evidence_needed="Spot volume, spread, market depth/slippage, concentration and manipulation checks",
            cross_venue_price_check="NOT_DONE", production_approval="NO",
            recommended_action="MANUAL_IDENTITY_AND_LIQUIDITY_REVIEW"))
    result.sort(key=lambda r: (-float(r["radar_score"] or 0), -r["source_count"], r["symbol"]))
    for i, r in enumerate(result, 1):
        r["priority_rank"] = i
    return result


def write(before_path, coverage_path, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = report(read(before_path), read(coverage_path))
    with (out / "incremental_cex_identity_readiness.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    info = {"incremental_candidate_count": len(rows),
            "unique_exchange_sources": dict(sorted(Counter(v for r in rows for v in r["candidate_sources"].split(";")).items())),
            "verified_identity_count": 0, "approved_imports": 0,
            "status": "RESEARCH_ONLY",
            "critical_note": "All markets provisional; ticker and OHLCV do not prove asset identity. No automated approvals or imports."}
    (out / "incremental_cex_identity_readiness.json").write_text(json.dumps(info, indent=2) + "\n")
    return info


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--before-after", default="reports/expanded_cex_before_after.csv")
    p.add_argument("--coverage", default="reports/expanded_cex_coverage.csv")
    p.add_argument("--out", default="reports/identity_readiness")
    args = p.parse_args()
    print(json.dumps(write(args.before_after, args.coverage, args.out), indent=2))
