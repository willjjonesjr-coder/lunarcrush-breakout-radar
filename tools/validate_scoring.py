"""Offline, deterministic scoring and historical forward-return checks.

No API calls. Uses saved daily history files and the same feature/scoring code.
Forward returns are descriptive, not a claim of out-of-sample predictive accuracy.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scanner import feature_row, score_candidates, load_config

def run(data_dir="data", reports_dir="reports", min_history=45):
    cfg = load_config()
    source = Path(reports_dir) / "breakout_radar.csv"
    candidates = pd.read_csv(source, dtype={"id": str})
    if not len(candidates):
        raise ValueError("Empty candidate report")
    baseline = score_candidates(candidates, cfg).set_index("id")
    shuffled = score_candidates(candidates.sample(frac=1, random_state=42), cfg).set_index("id")
    cols = ["breakout_score"] + [c for c in baseline if c.endswith("_score")]
    delta = (baseline[cols].sort_index() - shuffled[cols].sort_index()).abs().max().max()
    if not np.isfinite(delta) or delta > 1e-9:
        raise AssertionError(f"Scoring changes when candidate order changes: {delta}")
    # A changed candidate universe must not change scores for the same feature rows.
    subset = score_candidates(candidates.iloc[:max(1, len(candidates)//2)], cfg).set_index("id")
    subset_delta = (baseline.loc[subset.index, cols] - subset[cols]).abs().max().max()
    if not np.isfinite(subset_delta) or subset_delta > 1e-9:
        raise AssertionError(f"Scoring changes when universe shrinks: {subset_delta}")

    # Historical replay: score using ONLY rows available at each past cutoff.
    # Select cutoffs with at least 30 prior days and 7 or 14 future days.
    replay = []
    for _, coin in candidates.iterrows():
        path = Path(data_dir) / f"history_{coin['id']}.csv"
        if not path.exists():
            continue
        h = pd.read_csv(path)
        if "time" not in h or "close" not in h:
            continue
        h["time"] = pd.to_datetime(h["time"], utc=True)
        h = h.sort_values("time").drop_duplicates("time")
        h = h[h.time < pd.Timestamp.now("UTC").normalize()].copy()
        if len(h) < min_history:
            continue
        for horizon in (7, 14):
            for pos in range(35, len(h) - horizon, 14):
                past = h.iloc[:pos+1].copy()
                feat = feature_row(past)
                if feat is None:
                    continue
                price0 = pd.to_numeric(h["close"].iloc[pos], errors="coerce")
                price1 = pd.to_numeric(h["close"].iloc[pos+horizon], errors="coerce")
                if not np.isfinite(price0) or price0 <= 0 or not np.isfinite(price1):
                    continue
                feat.update({"id": str(coin["id"]), "symbol": coin.get("symbol"),
                             "name": coin.get("name"), "low_liquidity_flag": coin.get("low_liquidity_flag", False),
                             "recent_pump_flag": False})
                scored = score_candidates(pd.DataFrame([feat]), cfg).iloc[0]
                replay.append({"id": str(coin["id"]), "symbol": coin.get("symbol"),
                               "cutoff_utc": h["time"].iloc[pos].isoformat(),
                               "horizon_days": horizon, "score": float(scored.breakout_score),
                               "stage": scored.stage, "asset_type": scored.asset_type,
                               "forward_return": float(price1/price0-1)})
    out = Path(reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    replay_df = pd.DataFrame(replay)
    replay_df.to_csv(out/"historical_forward_returns.csv", index=False)
    summary = {"normalization_version": "fixed-provisional-v1",
               "order_invariance_max_delta": float(delta),
               "population_invariance_max_delta": float(subset_delta),
               "historical_observations": len(replay_df),
               "limitations": ["Survivorship bias: current candidates only",
                               "Overlapping windows; observations are not independent",
                               "No fees, slippage or tradability screen",
                               "No matched market benchmark or independent identity verification"]}
    if len(replay_df):
        summary["by_horizon_and_score"] = []
        replay_df["score_band"] = pd.cut(replay_df.score, [-1,45,55,65,75,101],
                                          labels=["<45","45-54","55-64","65-74","75+"])
        for (horizon, band), group in replay_df.groupby(["horizon_days","score_band"], observed=True):
            summary["by_horizon_and_score"].append({
                "horizon_days": int(horizon), "score_band": str(band),
                "n": len(group), "mean_return": float(group.forward_return.mean()),
                "median_return": float(group.forward_return.median()),
                "positive_rate": float((group.forward_return > 0).mean())})
    (out/"controlled_validation.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return summary

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="data")
    p.add_argument("--reports-dir", default="reports")
    args = p.parse_args()
    run(args.data_dir, args.reports_dir)
