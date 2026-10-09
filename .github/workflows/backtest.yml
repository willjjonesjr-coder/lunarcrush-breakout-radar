import argparse
from pathlib import Path

import numpy as np
import pandas as pd


FEATURES = [
    "contributors_active",
    "contributors_created",
    "interactions",
    "posts_active",
    "posts_created",
    "sentiment",
    "spam",
    "close",
    "galaxy_score",
    "social_dominance",
    "volume_24h",
]

STRATEGY_CONFIG = {
    "baseline": {
        "label": "baseline",
        "price_cap_7d": None,
        "price_cap_30d": None,
        "price_cap_90d": None,
        "extension_penalty_mult": 0.0,
        "price_distance_filter": None,  # e.g. 0.10 means no more than 10% below recent high
    },
    "moderate": {
        "label": "moderate",
        "price_cap_7d": 0.25,       # exclude > +25% in 7d
        "price_cap_30d": None,
        "price_cap_90d": None,
        "extension_penalty_mult": 0.35,
        "price_distance_filter": None,
    },
    "strict": {
        "label": "strict",
        "price_cap_7d": 0.15,       # exclude > +15% in 7d
        "price_cap_30d": 0.60,      # exclude > +60% in 30d
        "price_cap_90d": 1.50,      # exclude > +150% in 90d
        "extension_penalty_mult": 0.35,
        "price_distance_filter": 0.10,  # exclude if >10% below recent 7d high
    },
}


def load_history(path):
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for c in FEATURES:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("time").drop_duplicates("time").reset_index(drop=True)


def rolling_accel(s, short=7, base=23):
    short_mean = s.rolling(short, min_periods=3).mean()
    base_mean = s.shift(short).rolling(base, min_periods=8).mean()
    return short_mean / base_mean.replace(0, np.nan) - 1


def pct_change_window(series, periods):
    return series.pct_change(periods=periods).replace([np.inf, -np.inf], np.nan)


def anti_pump_mask(x, cfg):
    """
    Anti-pump filters used in the live scanner backtest.
    The default baseline strategy leaves these filters off.
    """
    mask = pd.Series(True, index=x.index)

    # 7-day price cap (live scanner rule: max +35% in 7d)
    if cfg["price_cap_7d"] is not None:
        mask &= x["price_change_7d"].fillna(0) <= cfg["price_cap_7d"]

    # Optional 30d / 90d ceiling for strict mode
    if cfg["price_cap_30d"] is not None:
        mask &= x["price_change_30d"].fillna(0) <= cfg["price_cap_30d"]

    if cfg["price_cap_90d"] is not None:
        mask &= x["price_change_90d"].fillna(0) <= cfg["price_cap_90d"]

    # Optional "distance from recent high" guard
    if cfg["price_distance_filter"] is not None:
        # price is too far below its recent 7d high -> likely extended / already run
        mask &= x["distance_from_7d_high"].fillna(1.0) >= -cfg["price_distance_filter"]

    return mask


def make_features(h, strategy="baseline"):
    x = h.copy()

    if "close" in x:
        x["close"] = pd.to_numeric(x["close"], errors="coerce")
        x["price_change_7d"] = x["close"] / x["close"].shift(7) - 1
        x["price_change_30d"] = x["close"] / x["close"].shift(30) - 1
        x["price_change_90d"] = x["close"] / x["close"].shift(90) - 1

        # Recent price high tracking to catch extended moves
        x["recent_7d_high"] = x["close"].rolling(7, min_periods=2).max()
        x["distance_from_7d_high"] = (x["close"] - x["recent_7d_high"]) / x["recent_7d_high"].replace(0, np.nan)

    # Social / engagement acceleration features
    x["social_accel"] = rolling_accel(x["posts_active"])
    x["contributor_accel"] = rolling_accel(x["contributors_active"])
    x["engagement_accel"] = rolling_accel(x["interactions"])
    x["volume_accel"] = rolling_accel(x["volume_24h"])

    # Price/sentiment trend features
    x["sentiment_change"] = x["sentiment"] - x["sentiment"].shift(7)
    x["social_dom_change"] = (
        x["social_dominance"] / x["social_dominance"].shift(7).replace(0, np.nan) - 1
    )
    x["price_change_7d"] = x.get("price_change_7d", pd.Series(np.nan, index=x.index))
    x["social_price_divergence"] = (
        (x[["social_accel", "contributor_accel", "engagement_accel"]].mean(axis=1))
        - x["price_change_7d"].clip(lower=0)
    )

    # Match the live scanner's overall weighting idea without hard cross-sectional
    # normalization, then apply strategy-specific anti-pump penalty.
    base_signal = (
        25 * x["social_accel"].clip(-1, 3).fillna(0) / 3
        + 15 * x["contributor_accel"].clip(-1, 3).fillna(0) / 3
        + 15 * x["engagement_accel"].clip(-1, 3).fillna(0) / 3
        + 10 * (x["sentiment_change"].clip(-30, 30).fillna(0) / 30)
        + 10 * x["social_dom_change"].clip(-1, 3).fillna(0) / 3
        + 10 * x["volume_accel"].clip(-1, 3).fillna(0) / 3
        + 15 * x["social_price_divergence"].clip(-1, 3).fillna(0) / 3
    )

    cfg = STRATEGY_CONFIG[strategy]
    ext_mult = cfg["extension_penalty_mult"]

    # This mirrors the live scanner's anti-pump rule:
    # +1% 7d gain -> -0.35 score points; cap at 25 points
    x["price_extension_penalty"] = (
        x["price_change_7d"].clip(lower=0).fillna(0) * 100 * ext_mult
    ).clip(upper=25)

    x["base_signal_score"] = base_signal
    x["signal_score"] = base_signal - x["price_extension_penalty"]

    # Apply anti-pump selection mask
    x["keep"] = anti_pump_mask(x, cfg)

    return x


def events_for(x, threshold, horizon, coin, strategy="baseline"):
    if horizon < 1:
        raise ValueError("Horizon must be at least 1")

    price = x["close"]
    future = price.shift(-horizon) / price - 1
    drawdown = (price.rolling(horizon, min_periods=horizon).min().shift(-horizon) / price - 1).clip(upper=0)

    valid = (
        x["keep"]
        & (x["signal_score"] >= threshold)
        & (price > 0)
        & np.isfinite(future)
        & np.isfinite(drawdown)
    )

    out = pd.DataFrame(
        {
            "signal_time": x["time"],
            "signal_score": x["signal_score"],
            "entry_price": price,
            "forward_return": future,
            "max_forward_drawdown": drawdown,
            "price_change_7d": x["price_change_7d"],
            "price_change_30d": x["price_change_30d"],
            "price_change_90d": x["price_change_90d"],
            "base_signal_score": x["base_signal_score"],
            "price_extension_penalty": x["price_extension_penalty"],
        }
    )[valid].copy()

    out["coin_file"] = coin
    out["threshold"] = threshold
    out["horizon"] = horizon
    out["strategy"] = strategy
    return out


def summarize(events):
    if events.empty:
        return {
            "signals": 0,
            "coins_with_signals": 0,
            "hit_10pct": np.nan,
            "hit_20pct": np.nan,
            "hit_50pct": np.nan,
            "mean_forward_return": np.nan,
            "median_forward_return": np.nan,
            "worst_forward_return": np.nan,
            "mean_max_forward_drawdown": np.nan,
            "worst_max_forward_drawdown": np.nan,
        }

    r = events["forward_return"]
    dd = events["max_forward_drawdown"]
    return {
        "signals": len(events),
        "coins_with_signals": events["coin_file"].nunique(),
        "hit_10pct": (r >= 0.10).mean(),
        "hit_20pct": (r >= 0.20).mean(),
        "hit_50pct": (r >= 0.50).mean(),
        "mean_forward_return": r.mean(),
        "median_forward_return": r.median(),
        "worst_forward_return": r.min(),
        "mean_max_forward_drawdown": dd.mean(),
        "worst_max_forward_drawdown": dd.min(),
    }


def evaluate_histories(histories, strategy, thresholds, horizons):
    all_events, per_coin, matrix = [], [], []

    for threshold in thresholds:
        for horizon in horizons:
            chunks, eligible = [], 0
            for coin, h in histories.items():
                if len(h) < max(45, horizon + 14):
                    continue
                eligible += 1

                h_feat = make_features(h, strategy=strategy)
                events = events_for(h_feat, threshold, horizon, coin, strategy=strategy)
                chunks.append(events)
                per_coin.append(
                    {
                        "strategy": strategy,
                        "threshold": threshold,
                        "horizon": horizon,
                        "coin_file": coin,
                        **summarize(events),
                    }
                )

            if chunks:
                events = pd.concat(chunks, ignore_index=True)
            else:
                # No valid signals for this threshold/horizon; keep shape stable
                events = pd.DataFrame(
                    columns=[
                        "signal_time",
                        "signal_score",
                        "entry_price",
                        "forward_return",
                        "max_forward_drawdown",
                        "price_change_7d",
                        "price_change_30d",
                        "price_change_90d",
                        "base_signal_score",
                        "price_extension_penalty",
                        "coin_file",
                        "threshold",
                        "horizon",
                        "strategy",
                    ]
                )

            all_events.append(events)
            matrix.append(
                {
                    "strategy": strategy,
                    "threshold": threshold,
                    "horizon": horizon,
                    "coins_loaded": len(histories),
                    "coins_eligible": eligible,
                    **summarize(events),
                }
            )

    summary = pd.DataFrame(matrix)
    per_coin_df = pd.DataFrame(per_coin)
    all_events_df = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()

    return summary, per_coin_df, all_events_df


def parse_thresholds(s):
    return sorted(set(float(t) for t in s.split(","))) if s else [25.0]


def parse_horizons(s):
    return sorted(set(int(h) for h in s.split(","))) if s else [14]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="reports/backtest.csv")
    parser.add_argument("--thresholds", default="20,25,30,35,40")
    parser.add_argument("--horizons", default="7,14,30")
    parser.add_argument("--strategy", choices=["baseline", "moderate", "strict", "all"], default="all")
    parser.add_argument("--min-history-length", type=int, default=45)
    args = parser.parse_args()

    thresholds = parse_thresholds(args.thresholds)
    horizons = parse_horizons(args.horizons)

    if not thresholds or not horizons or any(h < 1 for h in horizons):
        parser.error("Use positive horizons and finite thresholds.")

    data_dir = Path(args.data_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    paths = sorted(data_dir.glob("history_*.csv"))
    if not paths:
        raise SystemExit("No history files found. Run scanner first.")

    histories = {}
    for path in paths:
        try:
            h = load_history(path)
            histories[path.name] = h
        except Exception as exc:
            print(f"[WARN] Skipping {path.name}: {exc}")

    if not histories:
        raise SystemExit("No usable histories.")

    strategies = [args.strategy] if args.strategy != "all" else ["baseline", "moderate", "strict"]

    all_summary = []
    all_per_coin = []
    all_events = []

    for strat in strategies:
        summary, per_coin, events = evaluate_histories(histories, strat, thresholds, horizons)
        all_summary.append(summary)
        all_per_coin.append(per_coin)
        all_events.append(events)

        prefix = output.with_suffix("")
        strategy_out = Path(str(prefix) + f"_{strat}")
        summary.to_csv(str(strategy_out) + "_matrix.csv", index=False)
        per_coin.to_csv(str(strategy_out) + "_per_coin.csv", index=False)
        if not events.empty:
            events.to_csv(str(strategy_out) + "_events.csv", index=False)

        print(f"\n=== {STRATEGY_CONFIG[strat]['label'].upper()} STRATEGY ===")
        print(summary.to_string(index=False))
        print(
            "Research only: overlapping signals, current-universe selection bias, revised data; "
            "no fees/slippage. Horizons count observations, not calendar days. "
            "Drawdown is daily-close loss relative to the signal entry."
        )

    comparison = pd.concat(all_summary, ignore_index=True)
    out_comp = output.with_suffix("")
    comparison.to_csv(str(out_comp) + "_comparison.csv", index=False)

    # Also save a combined per-coin file
    combined_per_coin = pd.concat(all_per_coin, ignore_index=True)
    combined_per_coin.to_csv(str(out_comp) + "_comparison_per_coin.csv", index=False)

    print("\n=== SUMMARY COMPARISON ===")
    print(comparison.to_string(index=False))

    print(f"\nSaved comparison outputs to: {out_comp}_comparison.csv")
    print(f"Saved per-coin comparison to: {out_comp}_comparison_per_coin.csv")


if __name__ == "__main__":
    main()
