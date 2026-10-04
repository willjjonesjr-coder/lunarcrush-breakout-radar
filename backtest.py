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


def make_features(h):
    x = h.copy()

    x["social_accel"] = rolling_accel(x["posts_active"])
    x["contributor_accel"] = rolling_accel(x["contributors_active"])
    x["engagement_accel"] = rolling_accel(x["interactions"])
    x["volume_accel"] = rolling_accel(x["volume_24h"])

    x["sentiment_change"] = x["sentiment"] - x["sentiment"].shift(7)
    x["social_dom_change"] = (
        x["social_dominance"] / x["social_dominance"].shift(7).replace(0, np.nan) - 1
    )

    x["price_change_7d"] = x["close"] / x["close"].shift(7) - 1

    social = x[
        ["social_accel", "contributor_accel", "engagement_accel"]
    ].mean(axis=1)

    x["social_price_divergence"] = social - x["price_change_7d"].clip(lower=0)

    # Cross-sectional normalization isn't available inside one coin's history,
    # so this backtest uses fixed thresholds for the initial research pass.
    x["signal_score"] = (
        25 * x["social_accel"].clip(-1, 3).fillna(0) / 3 +
        15 * x["contributor_accel"].clip(-1, 3).fillna(0) / 3 +
        15 * x["engagement_accel"].clip(-1, 3).fillna(0) / 3 +
        10 * (x["sentiment_change"].clip(-30, 30).fillna(0) / 30) +
        10 * x["social_dom_change"].clip(-1, 3).fillna(0) / 3 +
        10 * x["volume_accel"].clip(-1, 3).fillna(0) / 3 +
        15 * x["social_price_divergence"].clip(-1, 3).fillna(0) / 3
    )

    return x


def evaluate(h, threshold, horizon):
    if horizon < 1:
        raise ValueError("Horizon must be at least 1")
    x = make_features(h)

    future = x["close"].shift(-horizon) / x["close"] - 1
    future_min = x["close"].rolling(horizon).min().shift(-horizon) / x["close"] - 1

    future_min = future_min.clip(upper=0)

    signals = x["signal_score"] >= threshold
    valid = signals & future.notna()

    if valid.sum() == 0:
        return None

    r = future[valid]
    dd = future_min[valid]

    return {
        "signals": int(valid.sum()),
        "hit_10pct": float((r >= 0.10).mean()),
        "hit_20pct": float((r >= 0.20).mean()),
        "hit_50pct": float((r >= 0.50).mean()),
        "mean_forward_return": float(r.mean()),
        "median_forward_return": float(r.median()),
        "worst_forward_return": float(r.min()),
        "mean_max_forward_drawdown": float(dd.mean()),
        "worst_max_forward_drawdown": float(dd.min()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--threshold", type=float, default=25)
    parser.add_argument("--horizon", type=int, default=14)
    parser.add_argument("--output", default="reports/backtest.csv")
    args = parser.parse_args()

    paths = sorted(Path(args.data_dir).glob("history_*.csv"))
    if not paths:
        raise SystemExit("No history_*.csv files found. Run scanner.py first.")

    rows = []
    for path in paths:
        try:
            h = load_history(path)
            if len(h) < max(45, args.horizon + 14):
                continue
            result = evaluate(h, args.threshold, args.horizon)
            if result:
                result["coin_file"] = path.name
                rows.append(result)
        except Exception as exc:
            print(f"[WARN] {path.name}: {exc}")

    if not rows:
        raise SystemExit("No valid backtest results.")

    out = pd.DataFrame(rows)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index=False)
    print(out.to_string(index=False))

    print("\nPortfolio-style aggregate:")
    print(f"Coins tested: {len(out)}")
    print(f"Mean 10% hit rate: {out.hit_10pct.mean():.1%}")
    print(f"Mean 20% hit rate: {out.hit_20pct.mean():.1%}")
    print(f"Mean forward return: {out.mean_forward_return.mean():.2%}")
    print(f"Mean max forward drawdown: {out.mean_max_forward_drawdown.mean():.2%}")


if __name__ == "__main__":
    main()
