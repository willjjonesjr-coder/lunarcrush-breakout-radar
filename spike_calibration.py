"""Point-in-time comparison of production spike weights; research only.\n\nThe zero-weight variant retains production data-eligibility requirements and\nis not an exact reconstruction of the historical pre-spike scanner.\n"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scanner import feature_row, score_candidates

MODELS = {"trend_only": 0.0, "production_50": 0.5, "spike_75": 0.75}
HORIZONS = (7, 14, 30)

def histories(folder):
    for path in sorted(Path(folder).glob("history_*.csv")):
        try:
            df = pd.read_csv(path)
            if "time" not in df or "close" not in df:
                continue
            df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce").dt.floor("D")
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["time"]).sort_values("time").drop_duplicates("time", keep="last")
            if len(df) >= 40:
                yield path.stem[8:], df.reset_index(drop=True)
        except (ValueError, OSError, pd.errors.ParserError):
            continue

def observations(folder):
    rows = []
    for coin, hist in histories(folder):
        by_day = hist.set_index("time")
        # End of each signal day is the next UTC midnight; no partial day included.
        for i in range(30, len(hist)):
            day = hist.loc[i, "time"]
            features = feature_row(hist.iloc[:i+1].copy(), as_of=day + pd.Timedelta(days=1))
            if features is None:
                continue
            row = {"coin_id": coin, "time": day, **features}
            price = hist.loc[i, "close"]
            for horizon in HORIZONS:
                future = by_day["close"].get(day + pd.Timedelta(days=horizon), np.nan)
                row[f"return_{horizon}d"] = float(future / price - 1) if pd.notna(price) and price > 0 and pd.notna(future) and future > 0 else np.nan
            rows.append(row)
    return pd.DataFrame(rows)

def run(args):
    events = observations(args.data_dir)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if events.empty:
        raise SystemExit("No usable historical observations; no calibration result produced.")
    cfg = json.loads(Path(args.config).read_text())
    dates = sorted(events.time.unique())
    if len(dates) < 30:
        raise SystemExit("Insufficient distinct dates for chronological calibration.")
    split = dates[int(len(dates)*0.7)]
    scored = []
    for day, group in events.groupby("time"):
        for name, share in MODELS.items():
            config = {**cfg, "daily_spikes": {**cfg.get("daily_spikes", {}), "score_share": share}}
            ranked = score_candidates(group.copy(), config)
            ranked["model"] = name
            ranked["period"] = "holdout" if day >= split else "development"
            ranked["rank_on_day"] = ranked["breakout_score"].rank(ascending=False, method="first")
            scored.append(ranked[["coin_id", "time", "model", "period", "breakout_score", "rank_on_day", "daily_spike_flag", *[f"return_{h}d" for h in HORIZONS]]])
    data = pd.concat(scored, ignore_index=True)\n    # Daily ranks are assigned before forward-return availability is considered.
    data.to_csv(out / "spike_calibration_events.csv", index=False)
    summary = []
    for (model, period), group in data.groupby(["model", "period"]):
        for horizon in HORIZONS:
            valid = group.dropna(subset=["breakout_score", f"return_{horizon}d"]).copy()
            # Top 10 per day, never selecting on forward returns.
            top = valid[valid.rank_on_day <= 10]
            for subset_name, sample in [("all_scored", valid), ("daily_top_10", top)]:
                returns = sample[f"return_{horizon}d"]
                summary.append({"model": model, "period": period, "horizon_days": horizon,
                    "selection": subset_name, "observations": len(sample),
                    "distinct_days": sample.time.nunique(),
                    "mean_return": returns.mean() if len(sample) else np.nan,
                    "median_return": returns.median() if len(sample) else np.nan,
                    "positive_rate": (returns > 0).mean() if len(sample) else np.nan,
                    "breakout_10pct_rate": (returns >= .10).mean() if len(sample) else np.nan,
                    "breakout_20pct_rate": (returns >= .20).mean() if len(sample) else np.nan})
    pd.DataFrame(summary).to_csv(out / "spike_calibration_summary.csv", index=False)
    manifest = {"split_date": str(pd.Timestamp(split).date()), "models": MODELS,
        "horizons": HORIZONS, "signal_days": len(dates), "coins": events.coin_id.nunique(),
        "limitations": ["Zero-weight model retains production daily-spike data eligibility", "Survivorship/selection bias: only saved histories", "Overlapping signals",
            "No fees, slippage, or trade execution simulation", "Historical data may be revised",
            "Historical cross-sectional universe differs from live snapshot funnel",
            "Holdout is chronological, but model variants were preselected"]}
    (out / "spike_calibration_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    print(pd.DataFrame(summary).query("period == 'holdout' and selection == 'daily_top_10'").to_string(index=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output-dir", default="reports")
    run(parser.parse_args())
