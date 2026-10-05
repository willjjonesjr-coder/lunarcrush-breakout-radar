import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from lunarcrush_client import LunarCrushClient


def load_config(path="config.json"):
    return json.loads(Path(path).read_text())


def safe_num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def fetch_universe(client, cfg):
    page_size = min(1000, int(cfg["universe"]["page_size"]))
    rows = []
    page = 0

    while True:
        payload = client.get(
            "/public/coins/list/v1",
            params={"limit": page_size, "page": page, "sort": "market_cap_rank"}
        )
        data = payload.get("data", [])
        if not data:
            break
        rows.extend(data)

        total = payload.get("config", {}).get("total_rows")
        if len(data) < page_size or (total is not None and len(rows) >= int(total)):
            break
        page += 1

    return pd.DataFrame(rows)


def snapshot_filter(df, cfg):
    u = cfg["universe"]
    out = df.copy()

    for c in ["market_cap", "volume_24h", "percent_change_7d", "price", "social_volume_24h",
              "interactions_24h", "social_dominance", "sentiment", "galaxy_score",
              "alt_rank"]:
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    out = out[
        (out["market_cap"] >= u["min_market_cap"]) &
        (out["market_cap"] <= u["max_market_cap"]) &
        (out["volume_24h"] >= u["min_volume_24h"])
    ]

    if "percent_change_7d" in out:
        out = out[out["percent_change_7d"] <= u["max_7d_price_change"]]

    if "symbol" in out:
        out = out[~out["symbol"].isin(set(u["exclude_symbols"]))]

    # Cheap snapshot score. This is only the funnel, not the final model.
    out["snapshot_score"] = (
        pct_rank(out["volume_24h"]) * 0.25 +
        pct_rank(out["social_volume_24h"]) * 0.20 +
        pct_rank(out["interactions_24h"]) * 0.20 +
        pct_rank(out["social_dominance"]) * 0.10 +
        pct_rank(out["sentiment"]) * 0.10 +
        pct_rank(out["galaxy_score"]) * 0.15
    ) * 100

    return out.sort_values("snapshot_score", ascending=False)


def pct_rank(s):
    return s.rank(pct=True).fillna(0.0)


def fetch_history(client, coin_id, cfg):
    hist = cfg["history"]
    days = int(hist["lookback_days"])
    end = int(pd.Timestamp.utcnow().timestamp())
    start = int((pd.Timestamp.utcnow() - pd.Timedelta(days=days)).timestamp())

    payload = client.get(
        f"/public/coins/{coin_id}/time-series/v2",
        params={
            "bucket": hist["bucket"],
            "start": start,
            "end": end
        }
    )
    data = payload.get("data", [])
    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df["coin_id"] = str(coin_id)
    return df.sort_values("time").drop_duplicates("time")


def acceleration_ratio(series, short=7, long=30):
    short_mean = series.rolling(short, min_periods=max(2, short // 2)).mean()
    long_mean = series.rolling(long, min_periods=max(5, long // 3)).mean()
    return (short_mean / long_mean.replace(0, np.nan)) - 1.0


def pct_change_window(series, periods):
    return series.pct_change(periods=periods).replace([np.inf, -np.inf], np.nan)


def feature_row(hist):
    if len(hist) < 10:
        return None

    h = hist.copy()

    # Normalize names and numeric types.
    metrics = [
        "contributors_active", "contributors_created", "interactions",
        "posts_active", "posts_created", "sentiment", "spam",
        "alt_rank", "close", "galaxy_score", "market_cap",
        "social_dominance", "volume_24h"
    ]
    for c in metrics:
        if c in h:
            h[c] = pd.to_numeric(h[c], errors="coerce")

    # Social acceleration: current 7d average vs preceding 23d/30d context.
    def accel(c):
        if c not in h:
            return np.nan
        s = h[c]
        short = s.rolling(7, min_periods=3).mean()
        base = s.shift(7).rolling(23, min_periods=8).mean()
        return float((short.iloc[-1] / base.iloc[-1]) - 1) if base.iloc[-1] not in [0, np.nan] else np.nan

    def recent_change(c, n=7):
        if c not in h or len(h) <= n:
            return np.nan
        a, b = h[c].iloc[-1], h[c].iloc[-1-n]
        return float(a / b - 1) if b not in [0, np.nan] else np.nan

    out = {
        "social_accel": accel("posts_active"),
        "contributor_accel": accel("contributors_active"),
        "engagement_accel": accel("interactions"),
        "sentiment_change": recent_change("sentiment"),
        "social_dominance_change": recent_change("social_dominance"),
        "volume_accel": accel("volume_24h"),
        "price_change_7d": recent_change("close"),
        "price_change_30d": recent_change("close", 30),
        "galaxy_score_change": recent_change("galaxy_score"),
        "spam_change": recent_change("spam"),
        "last_price": float(h["close"].iloc[-1]) if "close" in h else np.nan,
        "last_time": h["time"].iloc[-1],
    }

    # Price divergence: strong social acceleration with modest price movement.
    social_components = [
        out["social_accel"], out["contributor_accel"], out["engagement_accel"]
    ]
    social_strength = np.nanmean([x for x in social_components if pd.notna(x)])
    out["social_price_divergence"] = (
        social_strength - max(0.0, out["price_change_7d"] or 0.0)
        if pd.notna(social_strength) and pd.notna(out["price_change_7d"])
        else np.nan
    )

    return out


def zscore_series(s):
    s = pd.to_numeric(s, errors="coerce")
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def score_candidates(df, cfg):
    out = df.copy()

    feature_weights = {
        "social_accel": 0.25,
        "contributor_accel": 0.15,
        "engagement_accel": 0.15,
        "sentiment_change": 0.10,
        "social_dominance_change": 0.10,
        "volume_accel": 0.10,
        "social_price_divergence": 0.10,
        "galaxy_score_change": 0.05,
    }

    score = 0
    for col, weight in feature_weights.items():
        z = zscore_series(out[col])
        # Logistic-like normalization: 0..100, robust to outliers.
        component = 50 + 15 * z.clip(-3, 3)
        out[f"{col}_score"] = component
        score = score + weight * component

    # Historical returns are fractions: 0.30 means a 30% gain.
    # Convert to percentage points before applying score-point penalties.
    out["extension_penalty"] = (
        out["price_change_7d"].clip(lower=0).fillna(0) * 100 * 0.35
    ).clip(upper=25)

    # Penalize extreme recent spam growth, but only modestly.
    out["spam_penalty"] = (
        out["spam_change"].clip(lower=0).fillna(0) * 5
    ).clip(upper=10)

    out["breakout_score"] = (
        score - out["extension_penalty"] - out["spam_penalty"]
    ).clip(0, 100)

    def stage(row):
        s = row["breakout_score"]
        p = row.get("price_change_7d", np.nan)
        if s >= 75 and pd.notna(p) and p < 0.15:
            return "PRE-BREAKOUT"
        if s >= 65:
            return "DEVELOPING"
        if s >= 55:
            return "BREAKOUT / MOMENTUM"
        if s >= 45:
            return "WATCH"
        return "WEAK"

    out["stage"] = out.apply(stage, axis=1)
    return out.sort_values("breakout_score", ascending=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--top", type=int, default=None)
    args = parser.parse_args()
    if args.top is not None and args.top < 1:
        parser.error("--top must be at least 1")

    cfg = load_config(args.config)
    data_dir = Path(cfg["output"]["data_dir"])
    report_dir = Path(cfg["output"]["reports_dir"])
    data_dir.mkdir(exist_ok=True)
    report_dir.mkdir(exist_ok=True)

    client = LunarCrushClient(
        base_url=cfg["base_url"],
        rpm=cfg["requests_per_minute"],
        daily_budget=cfg["daily_request_budget"],
    )

    universe = fetch_universe(client, cfg)
    universe.to_csv(data_dir / "universe_latest.csv", index=False)

    candidates = snapshot_filter(universe, cfg)
    n_hist = int(cfg["funnel"]["historical_candidates"])
    candidates = candidates.head(n_hist).copy()

    feature_rows = []
    for _, row in candidates.iterrows():
        coin_id = row["id"]
        try:
            hist = fetch_history(client, coin_id, cfg)
            if hist.empty:
                continue
            history_path = data_dir / f"history_{coin_id}.csv"
            if history_path.exists():
                previous = pd.read_csv(history_path)
                previous["time"] = pd.to_datetime(previous["time"], utc=True)
                hist = pd.concat([previous, hist], ignore_index=True)
                hist = hist.sort_values("time").drop_duplicates("time", keep="last")
            hist.to_csv(history_path, index=False)

            features = feature_row(hist)
            if features:
                features.update({
                    "id": coin_id,
                    "symbol": row.get("symbol"),
                    "name": row.get("name"),
                    "market_cap": row.get("market_cap"),
                    "snapshot_score": row.get("snapshot_score"),
                    "volume_24h_snapshot": row.get("volume_24h"),
                })
                feature_rows.append(features)
        except Exception as exc:
            print(f"[WARN] {row.get('symbol')} failed: {exc}")

    if not feature_rows:
        raise RuntimeError("No historical candidate data was returned.")

    result = score_candidates(pd.DataFrame(feature_rows), cfg)
    top_n = args.top or int(cfg["funnel"]["finalists"])
    result = result.head(top_n)

    result.to_csv(report_dir / "breakout_radar.csv", index=False)
    result.to_json(report_dir / "breakout_radar.json", orient="records", date_format="iso")

    cols = [
        "symbol", "name", "breakout_score", "stage",
        "social_accel", "contributor_accel", "engagement_accel",
        "sentiment_change", "social_dominance_change",
        "volume_accel", "price_change_7d", "social_price_divergence"
    ]
    print(result[[c for c in cols if c in result]].to_string(index=False))


if __name__ == "__main__":
    main()
