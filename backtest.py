import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd

from signals import feature_row, score_candidates, ema_features

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


def generate_daily_signal_rows(history_map):
    signal_rows = []

    for coin_id, hist in history_map.items():
        if hist.empty or len(hist) < 10:
            continue

        for idx in range(9, len(hist)):
            window = hist.iloc[: idx + 1].copy()
            features = feature_row(window)
            if features is None:
                continue

            # EMA features (partial when history is limited)
            ema = ema_features(window, require_200=False)

            row = {
                "coin_id": coin_id,
                "time": window["time"].iloc[-1],
                "last_price": float(features["last_price"]),
                "breakout_score": np.nan,
                "stage": None,
            }
            row.update(features)
            if ema:
                row.update(ema)
            signal_rows.append(row)

    if not signal_rows:
        return pd.DataFrame(columns=["coin_id", "time", "breakout_score", "stage", "last_price"]) 

    signal_df = pd.DataFrame(signal_rows)
    signal_df["time"] = pd.to_datetime(signal_df["time"], utc=True)

    scored = []
    for ts, grp in signal_df.groupby("time"):
        out = score_candidates(grp.copy())
        for _, row in out.iterrows():
            scored.append({
                "coin_id": row["coin_id"],
                "time": pd.Timestamp(ts),
                "breakout_score": float(row["breakout_score"]),
                "stage": row["stage"],
                "last_price": float(row.get("last_price", np.nan)),
                "price_change_7d": float(row.get("price_change_7d", np.nan)),
                "price_change_30d": float(row.get("price_change_30d", np.nan)),
                "social_accel": float(row.get("social_accel", np.nan)),
                "contributor_accel": float(row.get("contributor_accel", np.nan)),
                "engagement_accel": float(row.get("engagement_accel", np.nan)),
                "has_ema50": bool(row.get("has_ema50", False)),
                "has_ema100": bool(row.get("has_ema100", False)),
                "has_ema200": bool(row.get("has_ema200", False)),
                "distance_ema50": float(row.get("distance_ema50", np.nan)),
                "distance_ema100": float(row.get("distance_ema100", np.nan)),
                "distance_ema200": float(row.get("distance_ema200", np.nan)),
                "ema_convergence": float(row.get("ema_convergence", np.nan)),
                "ema50_slope_5d": float(row.get("ema50_slope_5d", np.nan)),
                "bullish_alignment": bool(row.get("bullish_alignment", False)),
                "near_ema50": bool(row.get("near_ema50", False)),
                "near_ema100": bool(row.get("near_ema100", False)),
                "near_ema200": bool(row.get("near_ema200", False)),
                "ema50_cross_recent": bool(row.get("ema50_cross_recent", False)),
            })

    return pd.DataFrame(scored)


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


def build_backtest_records(data_dir, thresholds, horizons, strategies, top_n=None):
    history_map = load_history_map(data_dir, top_n=top_n)
    signal_events = generate_daily_signal_rows(history_map)

    if signal_events.empty:
        return []

    enriched = []
    for _, row in signal_events.iterrows():
        hist = history_map.get(str(row["coin_id"]))
        if hist is None:
            continue
        signal_time = pd.Timestamp(row["time"])
        prior_7d = prior_return_for(hist, signal_time, 7)
        prior_30d = prior_return_for(hist, signal_time, 30)
        row_dict = row.to_dict()
        row_dict["prior_7d_return"] = prior_7d
        row_dict["prior_30d_return"] = prior_30d
        enriched.append(row_dict)

    enriched_df = pd.DataFrame(enriched)
    if enriched_df.empty:
        return []

    records = []
    for strategy in strategies:
        for threshold in thresholds:
            for horizon in horizons:
                hits = []
                for _, row in enriched_df.iterrows():
                    if row["breakout_score"] < threshold:
                        continue
                    if not filter_for_strategy(strategy, row.get("prior_7d_return"), row.get("prior_30d_return")):
                        continue

                    hist = history_map.get(str(row["coin_id"]))
                    if hist is None:
                        continue

                    forward_ret = forward_return_for(hist, pd.Timestamp(row["time"]), horizon)
                    if pd.isna(forward_ret):
                        continue

                    hit = row.to_dict()
                    hit["forward_return"] = forward_ret
                    hit["horizon_days"] = horizon
                    hit["strategy"] = strategy
                    hits.append(hit)

                if not hits:
                    records.append({
                        "strategy": strategy,
                        "threshold": threshold,
                        "horizon_days": horizon,
                        "signals": 0,
                        "avg_return": 0.0,
                        "hit_rate": 0.0,
                        "total_return": 0.0,
                    })
                    continue

                forward_returns = [float(r["forward_return"]) for r in hits]
                positive = [r for r in hits if r["forward_return"] > 0]
                records.append({
                    "strategy": strategy,
                    "threshold": threshold,
                    "horizon_days": horizon,
                    "signals": len(hits),
                    "avg_return": float(np.mean(forward_returns)),
                    "hit_rate": float(len(positive) / len(forward_returns)),
                    "total_return": float(np.sum(forward_returns)),
                })

    return records


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


def main():
    parser = argparse.ArgumentParser(description="Historical anti-pump backtest")
    parser.add_argument("--data-dir", default="data", help="Directory containing historical price files")
    parser.add_argument("--output", default="reports/backtest.csv", help="Output CSV path")
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
    records = build_backtest_records(args.data_dir, thresholds, horizons, strategies, top_n=args.top)
    write_csv(args.output, records)

    print(f"Backtest complete. Wrote {len(records)} rows to {args.output}")
    print(f"Strategy: {args.strategy}")
    print(f"Thresholds: {thresholds}")
    print(f"Horizons: {horizons}")

    if args.top is not None:
        print(f"Top N coins used: {args.top}")


if __name__ == "__main__":
    main()
