import argparse
import csv
from pathlib import Path

import time
import numpy as np
import pandas as pd

from signals import score_candidates
from backtest_features import historical_features

DEFAULT_THRESHOLDS = [20, 25, 30, 35, 40]
DEFAULT_HORIZONS = [7, 14, 30]


def parse_int_list(raw_value, default_list):
    if raw_value is None or str(raw_value).strip() == "":
        return list(default_list)

    values = []
    for item in str(raw_value).split(","):
        item = item.strip()
        if item:
            try:
                values.append(int(item))
            except ValueError:
                return list(default_list)
    return values if values else list(default_list)


def strategy_list(strategy):
    if strategy == "all":
        return ["baseline", "moderate", "strict"]
    return [strategy]


def load_history_map(data_dir, top_n=None):
    data_path = Path(data_dir)
    history_map = {}

    for file_path in sorted(data_path.glob("history_*.csv")):
        try:
            df = pd.read_csv(file_path)
        except Exception:
            continue
        if df.empty or "time" not in df.columns:
            continue

        df = df.copy()
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").drop_duplicates("time", keep="last")

        for col in [
            "contributors_active", "contributors_created", "interactions",
            "posts_active", "posts_created", "sentiment", "spam",
            "alt_rank", "close", "galaxy_score", "market_cap",
            "social_dominance", "volume_24h"
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        coin_id = file_path.stem.replace("history_", "")
        df["coin_id"] = coin_id
        history_map[coin_id] = df

    if top_n is not None:
        ranked = sorted(
            history_map.items(),
            key=lambda kv: float(kv[1]["market_cap"].iloc[-1]) if "market_cap" in kv[1].columns and not kv[1]["market_cap"].empty else 0.0,
            reverse=True,
        )
        history_map = {coin_id: hist for coin_id, hist in ranked[:top_n]}

    return history_map


def _report(progress, message):
    if progress is not None:
        progress(message)


def generate_daily_signal_rows(history_map, progress=None):
    """Compute each causal rolling/EMA series once, then score each date."""
    frames = []
    total = len(history_map)
    _report(progress, f"Computing historical features for {total} coins")
    for number, (coin_id, hist) in enumerate(history_map.items(), 1):
        if not hist.empty and len(hist) >= 10:
            features = historical_features(hist).reset_index(drop=True)
            features.insert(0, "coin_id", coin_id)
            features.insert(1, "time", hist["time"].iloc[9:].to_numpy())
            frames.append(features)
        if number % 50 == 0 or number == total:
            _report(progress, f"Features: {number}/{total} coins")

    if not frames:
        return pd.DataFrame(columns=["coin_id", "time", "breakout_score", "stage", "last_price"])

    signal_df = pd.concat(frames, ignore_index=True)
    signal_df["time"] = pd.to_datetime(signal_df["time"], utc=True)
    numeric_columns = [
        "breakout_score", "last_price", "price_change_7d", "price_change_30d",
        "social_accel", "contributor_accel", "engagement_accel",
        "distance_ema50", "distance_ema100", "distance_ema200",
        "ema_convergence", "ema50_slope_5d",
    ]
    bool_columns = [
        "has_ema50", "has_ema100", "has_ema200", "bullish_alignment",
        "near_ema50", "near_ema100", "near_ema200", "ema50_cross_recent",
    ]
    output_columns = [
        "coin_id", "time", "breakout_score", "stage", "last_price",
        "price_change_7d", "price_change_30d", "social_accel",
        "contributor_accel", "engagement_accel", "has_ema50", "has_ema100",
        "has_ema200", "distance_ema50", "distance_ema100", "distance_ema200",
        "ema_convergence", "ema50_slope_5d", "bullish_alignment", "near_ema50",
        "near_ema100", "near_ema200", "ema50_cross_recent",
    ]
    scored = []
    groups = signal_df.groupby("time")
    _report(progress, f"Scoring {len(signal_df)} signal rows across {len(groups)} dates")
    for number, (_, grp) in enumerate(groups, 1):
        # Keep the existing cross-sectional score, stage, and tie ordering.
        out = score_candidates(grp.copy())
        for col in numeric_columns:
            out[col] = out[col].astype(float) if col in out else np.nan
        for col in bool_columns:
            out[col] = out[col].astype(bool) if col in out else False
        scored.append(out[output_columns])
        if number % 100 == 0 or number == len(groups):
            _report(progress, f"Scored: {number}/{len(groups)} dates")
    return pd.concat(scored, ignore_index=True) if scored else pd.DataFrame(columns=output_columns)


def prior_return_for(history, signal_time, days):
    if history.empty or "close" not in history.columns:
        return np.nan
    past = history[history["time"] <= signal_time].copy()
    if past.empty:
        return np.nan

    current_close = past["close"].iloc[-1]
    target_time = signal_time - pd.Timedelta(days=days)
    window = past[past["time"] <= target_time]
    if window.empty:
        return np.nan
    prior_close = window["close"].iloc[-1]
    if pd.isna(current_close) or pd.isna(prior_close) or prior_close in [0, np.nan]:
        return np.nan
    return float(current_close / prior_close - 1.0)


def forward_return_for(history, signal_time, horizon_days):
    if history.empty or "close" not in history.columns:
        return np.nan
    past = history[history["time"] <= signal_time].copy()
    if past.empty:
        return np.nan
    current_close = past["close"].iloc[-1]
    target_time = signal_time + pd.Timedelta(days=horizon_days)
    future = history[history["time"] >= target_time].copy()
    if future.empty:
        return np.nan
    future_close = future["close"].iloc[0]
    if pd.isna(current_close) or pd.isna(future_close) or current_close in [0, np.nan]:
        return np.nan
    return float(future_close / current_close - 1.0)


def filter_for_strategy(strategy, prior_7d, prior_30d):
    if strategy == "baseline":
        return True
    if strategy == "moderate":
        return not (pd.notna(prior_7d) and prior_7d > 0.20)
    if strategy == "strict":
        return not (
            (pd.notna(prior_7d) and prior_7d > 0.12)
            or (pd.notna(prior_30d) and prior_30d > 0.40)
        )
    return True


def summarize_results(events, strategy, threshold, horizon):
    hits = []
    for _, row in events.iterrows():
        if row["breakout_score"] < threshold:
            continue
        if not filter_for_strategy(strategy, row.get("prior_7d_return"), row.get("prior_30d_return")):
            continue
        hits.append(row)

    if not hits:
        return {
            "strategy": strategy,
            "threshold": threshold,
            "horizon_days": horizon,
            "signals": 0,
            "avg_return": 0.0,
            "hit_rate": 0.0,
            "total_return": 0.0,
        }

    forward_returns = [float(r["forward_return"]) for r in hits if pd.notna(r.get("forward_return"))]
    positive = [r for r in hits if pd.notna(r.get("forward_return")) and r["forward_return"] > 0]

    avg_return = np.mean(forward_returns) if forward_returns else 0.0
    hit_rate = len(positive) / len(forward_returns) if forward_returns else 0.0
    total_return = float(np.sum(forward_returns)) if forward_returns else 0.0

    return {
        "strategy": strategy,
        "threshold": threshold,
        "horizon_days": horizon,
        "signals": len(hits),
        "avg_return": avg_return,
        "hit_rate": hit_rate,
        "total_return": total_return,
    }


def compute_tech_summary(hits, proximity_pct=0.05, conv_pct=0.05, extension_pct=0.15):
    """Compute experiment A..F over a list of hit dicts. Returns list of summary rows."""
    if len(hits) == 0:
        return []

    # hits is a DataFrame or list of dict-like rows with keys including forward_return and EMA fields
    df = hits if isinstance(hits, pd.DataFrame) else pd.DataFrame(hits)
    if df.empty or "forward_return" not in df.columns:
        return []

    def metrics(mask):
        sub = df[mask]
        if sub.empty:
            return {"signals": 0, "avg_return": 0.0, "median_return": 0.0, "hit_rate": 0.0, "total_return": 0.0}
        fr = sub["forward_return"].dropna().astype(float)
        if fr.empty:
            return {"signals": len(sub), "avg_return": 0.0, "median_return": 0.0, "hit_rate": 0.0, "total_return": 0.0}
        return {
            "signals": len(sub),
            "avg_return": float(fr.mean()),
            "median_return": float(fr.median()),
            "hit_rate": float((fr > 0).sum() / len(fr)),
            "total_return": float(fr.sum()),
        }

    # Conditions
    conds = {}
    conds["A_baseline"] = pd.Series(True, index=df.index)
    conds["B_proximity_5pct"] = (df.get("distance_ema50").abs() <= proximity_pct) | (df.get("distance_ema100").abs() <= proximity_pct)
    conds["C_convergence_5pct"] = df.get("ema_convergence") <= conv_pct
    conds["D_bullish_alignment"] = df.get("bullish_alignment") == True
    conds["E_combined"] = conds["C_convergence_5pct"] & conds["D_bullish_alignment"] & conds["B_proximity_5pct"]
    conds["F_anti_extension"] = ~(df.get("distance_ema50") > extension_pct)

    rows = []
    for name, mask in conds.items():
        m = mask.fillna(False) if isinstance(mask, pd.Series) else mask
        met = metrics(m)
        rows.append({
            "condition": name,
            **met
        })

    return rows


def write_per_signal_csv(path, hits):
    output_file = Path(path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if not hits:
        with output_file.open("w", newline="", encoding="utf-8") as f:
            f.write("")
        return

    # Normalize keys across hits
    all_keys = set()
    for h in hits:
        all_keys.update(h.keys())
    fieldnames = ["coin_id", "time"] + sorted(k for k in all_keys if k not in ("coin_id", "time"))

    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for h in hits:
            row = {k: h.get(k, "") for k in fieldnames}
            # Serialize timestamps
            if isinstance(row.get("time"), (pd.Timestamp,)):
                row["time"] = row["time"].isoformat()
            writer.writerow(row)


def indexed_returns(history, signal_times, days, forward=False):
    """Same calendar-time endpoints as the scalar helpers, with binary lookup.

    The loader sorts/deduplicates timestamps. Missing endpoint prices remain
    missing: this intentionally does not fill gaps or skip invalid closes.
    """
    result = np.full(len(signal_times), np.nan)
    if len(signal_times) == 0 or history.empty or "close" not in history:
        return result
    valid_history = history.loc[history["time"].notna()]
    if valid_history.empty:
        return result
    times = pd.DatetimeIndex(valid_history["time"])
    queries = pd.DatetimeIndex(signal_times)
    current = times.searchsorted(queries, side="right") - 1
    target = queries + pd.Timedelta(days=days if forward else -days)
    endpoint = times.searchsorted(target, side="left" if forward else "right")
    if not forward:
        endpoint = np.minimum(endpoint - 1, current)
    valid = (current >= 0) & (endpoint >= 0) & (endpoint < len(times)) & queries.notna()
    positions = np.flatnonzero(valid)
    closes = valid_history["close"].to_numpy(dtype=float)
    current_close = closes[current[valid]]
    other_close = closes[endpoint[valid]]
    numerator, denominator = (other_close, current_close) if forward else (current_close, other_close)
    with np.errstate(divide="ignore", invalid="ignore"):
        values = numerator / denominator - 1.0
    values[(denominator == 0) | pd.isna(numerator) | pd.isna(denominator)] = np.nan
    result[positions] = values
    return result


def enrich_signal_returns(signal_events, history_map, horizons, progress=None):
    enriched = signal_events.copy()
    enriched["prior_7d_return"] = np.nan
    enriched["prior_30d_return"] = np.nan
    forwards = {h: np.full(len(enriched), np.nan) for h in dict.fromkeys(horizons)}
    groups = enriched.groupby("coin_id", sort=False).indices
    _report(progress, f"Caching prior returns and {len(forwards)} forward horizons for {len(groups)} coins")
    for number, (coin_id, positions) in enumerate(groups.items(), 1):
        hist = history_map.get(str(coin_id))
        if hist is not None:
            times = enriched.iloc[positions]["time"]
            for days in (7, 30):
                enriched.loc[enriched.index[positions], f"prior_{days}d_return"] = indexed_returns(hist, times, days)
            for horizon in forwards:
                forwards[horizon][positions] = indexed_returns(hist, times, horizon, forward=True)
        if number % 100 == 0 or number == len(groups):
            _report(progress, f"Returns: {number}/{len(groups)} coins")
    return enriched, forwards


def _strategy_mask(events, strategy):
    if strategy == "moderate":
        return ~(events["prior_7d_return"] > 0.20)
    if strategy == "strict":
        return ~((events["prior_7d_return"] > 0.12) | (events["prior_30d_return"] > 0.40))
    return pd.Series(True, index=events.index)


def _write_hit_batch(handle, writer, hits):
    """Keep the legacy CSV column order, float formatting, and timestamps."""
    if hits.empty:
        return writer
    if writer is None:
        fields = ["coin_id", "time"] + sorted(c for c in hits if c not in ("coin_id", "time"))
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
    columns = hits.columns
    for values in hits.itertuples(index=False, name=None):
        row = dict(zip(columns, values))
        if isinstance(row.get("time"), pd.Timestamp):
            row["time"] = row["time"].isoformat()
        writer.writerow(row)
    return writer


def build_backtest_records(data_dir, thresholds, horizons, strategies, top_n=None,
                           progress=None, per_signal_path=None):
    """Return summaries/hits, or stream detail when per_signal_path is supplied.

    The default API still returns all hit dictionaries. The CLI streams the
    large detail CSV and retains only the five columns needed for the exact
    technical summary, including the original repeated threshold observations.
    """
    _report(progress, f"Loading history files from {data_dir}")
    history_map = load_history_map(data_dir, top_n=top_n)
    _report(progress, f"Loaded {len(history_map)} coins, {sum(len(h) for h in history_map.values())} observations")
    signal_events = generate_daily_signal_rows(history_map, progress=progress)
    handle = None
    if per_signal_path is not None:
        path = Path(per_signal_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", newline="", encoding="utf-8")
    try:
        if signal_events.empty:
            return [], [], []
        enriched, forwards = enrich_signal_returns(signal_events, history_map, horizons, progress)
        records, all_hits, tech_batches = [], [], []
        writer = None
        total = len(strategies) * len(thresholds) * len(horizons)
        completed = total_hits = 0
        tech_columns = ["forward_return", "distance_ema50", "distance_ema100", "ema_convergence", "bullish_alignment"]
        for strategy in strategies:
            strategy_mask = _strategy_mask(enriched, strategy)
            for threshold in thresholds:
                # NaN scores pass the legacy `if score < threshold: continue`.
                mask = strategy_mask & ~(enriched["breakout_score"] < threshold)
                for horizon in horizons:
                    selected = mask & pd.notna(forwards[horizon])
                    hits = enriched.loc[selected].copy()
                    returns = forwards[horizon][selected]
                    hits["forward_return"] = returns
                    hits["horizon_days"] = horizon
                    hits["strategy"] = strategy
                    if handle is None:
                        all_hits.extend(hits.to_dict("records"))
                    else:
                        writer = _write_hit_batch(handle, writer, hits)
                    if not hits.empty:
                        tech_batches.append(hits[tech_columns])
                    records.append({
                        "strategy": strategy, "threshold": threshold, "horizon_days": horizon,
                        "signals": len(hits),
                        "avg_return": float(np.mean(returns)) if len(returns) else 0.0,
                        "hit_rate": float(np.count_nonzero(returns > 0) / len(returns)) if len(returns) else 0.0,
                        "total_return": float(np.sum(returns)) if len(returns) else 0.0,
                    })
                    completed += 1
                    total_hits += len(hits)
                    _report(progress, f"Matrix {completed}/{total}: {strategy}, threshold={threshold}, horizon={horizon}d, {len(hits)} hits ({total_hits} detail rows)")
        _report(progress, f"Computing technical summary over {total_hits} detail rows")
        tech_summary = compute_tech_summary(pd.concat(tech_batches, ignore_index=True)) if tech_batches else []
        return records, all_hits, tech_summary
    finally:
        if handle is not None:
            handle.close()


def write_csv(output_path, records):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "strategy",
        "threshold",
        "horizon_days",
        "signals",
        "avg_return",
        "hit_rate",
        "total_return",
    ]

    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def write_tech_summary(path, rows):
    output_file = Path(path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["condition", "signals", "avg_return", "median_return", "hit_rate", "total_return"]
    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def main():
    parser = argparse.ArgumentParser(description="Historical anti-pump backtest")
    parser.add_argument("--data-dir", default="data", help="Directory containing historical price files")
    parser.add_argument("--output", default="reports/backtest.csv", help="Output CSV path")
    parser.add_argument("--per-signal", default="reports/backtest_per_coin.csv", help="Per-signal CSV output path")
    parser.add_argument("--tech-summary", default="reports/backtest_tech_summary.csv", help="Technical summary CSV path")
    parser.add_argument("--threshold", type=float, default=20, help="Single threshold")
    parser.add_argument("--horizon", type=int, default=7, help="Single horizon days")
    parser.add_argument("--thresholds", default=None, help="Comma-separated thresholds")
    parser.add_argument("--horizons", default=None, help="Comma-separated horizons")
    parser.add_argument("--strategy", choices=["all", "baseline", "moderate", "strict"], default="all")
    parser.add_argument("--matrix", action="store_true", help="Use full threshold/horizon matrix")
    parser.add_argument("--top", type=int, default=None, help="Optional limit to top N coins by latest market cap")

    args = parser.parse_args()

    if args.matrix or args.thresholds is not None:
        thresholds = parse_int_list(args.thresholds, DEFAULT_THRESHOLDS)
    else:
        thresholds = [int(args.threshold)]

    if args.matrix or args.horizons is not None:
        horizons = parse_int_list(args.horizons, DEFAULT_HORIZONS)
    else:
        horizons = [int(args.horizon)]

    strategies = strategy_list(args.strategy)
    started = time.perf_counter()

    def progress(message):
        print(f"[backtest {time.perf_counter() - started:.1f}s] {message}", flush=True)

    records, _, tech_summary = build_backtest_records(
        args.data_dir, thresholds, horizons, strategies, top_n=args.top,
        progress=progress, per_signal_path=args.per_signal,
    )
    progress("Writing summary CSVs")
    write_csv(args.output, records)
    write_tech_summary(args.tech_summary, tech_summary)
    progress(f"Finished all outputs in {time.perf_counter() - started:.1f}s")

    print(f"Backtest complete. Wrote {len(records)} rows to {args.output}")
    print(f"Strategy: {args.strategy}")
    print(f"Thresholds: {thresholds}")
    print(f"Horizons: {horizons}")

    if args.top is not None:
        print(f"Top N coins used: {args.top}")


if __name__ == "__main__":
    main()
