#!/usr/bin/env python3
"""Prioritize identity-review candidates for verified exchange OHLCV backfill.

This NEVER creates token mappings or counts provisional tickers as verified.
Run after production scanner: python tools/ema_expansion_queue.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
MAPPING = ROOT / "config" / "symbol_map.json"
FIELDS = ["review_rank", "coin_id", "symbol", "name", "breakout_score",
          "market_cap_usd", "volume_multiple_7d", "engagement_multiple_7d",
          "data_status", "review_status", "reason"]

def number(value):
    try:
        v = float(value)
        return v if v == v and abs(v) != float("inf") else 0.0
    except (TypeError, ValueError):
        return 0.0

def build(rows, mapped):
    candidates = []
    excluded = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "USDS", "USDD", "RLUSD", "WBTC", "WETH", "PAXG", "USDP"}
    for row in rows:
        coin_id = str(row.get("id", "")).strip()
        symbol = str(row.get("symbol", "")).strip().upper()
        if not coin_id or coin_id in mapped or symbol in excluded:
            continue
        if row.get("technical_status") != "INSUFFICIENT EMA HISTORY":
            continue
        cap = number(row.get("market_cap"))
        score = number(row.get("breakout_score"))
        vol = number(row.get("volume_spike_multiple"))
        eng = number(row.get("engagement_spike_multiple"))
        # Favor breakout potential and small capitalization without assuming
        # small-cap liquidity, exchange listing or token identity.
        cap_bonus = 10 if 0 < cap < 50_000_000 else (5 if 0 < cap < 250_000_000 else 0)
        acceleration_bonus = min(5, max(0, vol - 1) * 2) + min(5, max(0, eng - 1))
        priority = score + cap_bonus + acceleration_bonus
        candidates.append((priority, {
            "coin_id": coin_id, "symbol": symbol, "name": row.get("name", ""),
            "breakout_score": round(score, 3), "market_cap_usd": round(cap, 2),
            "volume_multiple_7d": round(vol, 3),
            "engagement_multiple_7d": round(eng, 3),
            "data_status": row.get("data_status", ""),
            "review_status": "UNVERIFIED — DO NOT USE FOR EMA",
            "reason": "Verify LunarCrush coin ID, contract/network and exchange base asset; require 300+ gapless completed UTC candles"
        }))
    candidates.sort(key=lambda item: (-item[0], -number(item[1]["breakout_score"]), item[1]["coin_id"]))
    result = []
    for i, (_, row) in enumerate(candidates, 1):
        result.append({"review_rank": i, **row})
    return result

def main():
    mapped = set(json.loads(MAPPING.read_text()))
    with (REPORTS / "breakout_radar.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    ranked = build(rows, mapped)
    with (REPORTS / "ema_expansion_review_queue.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ranked)
    summary = {"mapped_coin_ids": len(mapped), "unmapped_prioritized": len(ranked),
               "target_ema_evaluable": [100, 150],
               "first_review_batch": ranked[:80],
               "safety": "Review queue only. No inferred exchange mappings, synthetic candles, or alert eligibility changes."}
    (REPORTS / "ema_expansion_review_queue.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"EMA review queue: {len(ranked)} unmapped candidates; first batch 80")

if __name__ == "__main__":
    main()
