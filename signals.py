import numpy as np
import pandas as pd


def safe_num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def pct_rank(s):
    return s.rank(pct=True).fillna(0.0)


def zscore_series(s):
    s = pd.to_numeric(s, errors="coerce")
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def feature_row(hist):
    if len(hist) < 10:
        return None

    h = hist.copy()
    metrics = [
        "contributors_active", "contributors_created", "interactions",
        "posts_active", "posts_created", "sentiment", "spam",
        "alt_rank", "close", "galaxy_score", "market_cap",
        "social_dominance", "volume_24h"
    ]
    for c in metrics:
        if c in h:
            h[c] = pd.to_numeric(h[c], errors="coerce")

    def accel(c):
        if c not in h:
            return np.nan
        s = h[c]
        short = s.rolling(7, min_periods=3).mean()
        base = s.shift(7).rolling(23, min_periods=8).mean()
        curr = short.iloc[-1]
        ref = base.iloc[-1]
        if pd.isna(curr) or pd.isna(ref) or ref in [0, np.nan]:
            return np.nan
        return float(curr / ref - 1)

    def recent_change(c, n=7):
        if c not in h or len(h) <= n:
            return np.nan
        a, b = h[c].iloc[-1], h[c].iloc[-1 - n]
        if pd.isna(a) or pd.isna(b) or b in [0, np.nan]:
            return np.nan
        return float(a / b - 1)

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

    social_components = [
        out["social_accel"], out["contributor_accel"], out["engagement_accel"]
    ]
    social_strength = np.nanmean([x for x in social_components if pd.notna(x)]) if any(pd.notna(x) for x in social_components) else np.nan
    if pd.notna(social_strength) and pd.notna(out["price_change_7d"]):
        out["social_price_divergence"] = social_strength - max(0.0, out["price_change_7d"] or 0.0)
    else:
        out["social_price_divergence"] = np.nan

    return out


def ema_features(hist, require_200=False, proximity_pct=0.05, cross_lookback=10):
    """
    Compute EMA-based technical features for the provided historical DataFrame.
    Returns a dict with distance to EMAs, convergence metric, slopes, crosses, and flags indicating availability.

    Parameters:
    - hist: DataFrame with at least a 'close' and 'time' column sorted ascending by time
    - require_200: if True, return None when fewer than 200 observations exist
    - proximity_pct: threshold for 'near' EMA booleans (default 5%)
    - cross_lookback: lookback window (days) to detect recent EMA cross
    """
    if hist is None or hist.empty or "close" not in hist.columns:
        return None

    close = pd.to_numeric(hist["close"], errors="coerce").reset_index(drop=True)
    n = len(close)
    if require_200 and n < 200:
        return None

    res = {
        "has_ema50": False,
        "has_ema100": False,
        "has_ema200": False,
        "distance_ema50": np.nan,
        "distance_ema100": np.nan,
        "distance_ema200": np.nan,
        "ema_convergence": np.nan,
        "ema50_slope_5d": np.nan,
        "bullish_alignment": False,
        "near_ema50": False,
        "near_ema100": False,
        "near_ema200": False,
        "ema50_cross_recent": False,
    }

    price = close.iloc[-1]

    ema50 = ema100 = ema200 = None
    if n >= 50:
        ema50 = close.ewm(span=50, adjust=False).mean()
        res["has_ema50"] = True
    if n >= 100:
        ema100 = close.ewm(span=100, adjust=False).mean()
        res["has_ema100"] = True
    if n >= 200:
        ema200 = close.ewm(span=200, adjust=False).mean()
        res["has_ema200"] = True

    if ema50 is not None and not np.isnan(ema50.iloc[-1]):
        res["distance_ema50"] = float(price / ema50.iloc[-1] - 1.0)
    if ema100 is not None and not np.isnan(ema100.iloc[-1]):
        res["distance_ema100"] = float(price / ema100.iloc[-1] - 1.0)
    if ema200 is not None and not np.isnan(ema200.iloc[-1]):
        res["distance_ema200"] = float(price / ema200.iloc[-1] - 1.0)

    # Convergence only when all three EMAs exist
    if res["has_ema50"] and res["has_ema100"] and res["has_ema200"]:
        e_vals = [ema50.iloc[-1], ema100.iloc[-1], ema200.iloc[-1]]
        if not any(pd.isna(e) for e in e_vals):
            res["ema_convergence"] = float((max(e_vals) - min(e_vals)) / price)

    # EMA 50 slope over ~5 periods (compare to value 5 periods ago)
    if res["has_ema50"] and len(ema50) >= 6 and not np.isnan(ema50.iloc[-6]):
        res["ema50_slope_5d"] = float(ema50.iloc[-1] / ema50.iloc[-6] - 1.0)

    # Bullish alignment when all EMAs present and ordered
    if res["has_ema50"] and res["has_ema100"] and res["has_ema200"]:
        if (ema50.iloc[-1] > ema100.iloc[-1]) and (ema100.iloc[-1] > ema200.iloc[-1]):
            res["bullish_alignment"] = True

    # Near EMA booleans
    if not np.isnan(res["distance_ema50"]) and abs(res["distance_ema50"]) <= proximity_pct:
        res["near_ema50"] = True
    if not np.isnan(res["distance_ema100"]) and abs(res["distance_ema100"]) <= proximity_pct:
        res["near_ema100"] = True
    if not np.isnan(res["distance_ema200"]) and abs(res["distance_ema200"]) <= proximity_pct:
        res["near_ema200"] = True

    # Recent EMA50 cross above EMA100 in the last cross_lookback periods
    if res["has_ema50"] and res["has_ema100"]:
        diff = ema50 - ema100
        if len(diff) >= cross_lookback + 1:
            tail = diff.iloc[-(cross_lookback + 1):]
            crossed = ((tail.shift(1) <= 0) & (tail > 0)).fillna(False)
            if crossed.any():
                res["ema50_cross_recent"] = True

    return res


def score_candidates(df):
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

    score = 0.0
    for col, weight in feature_weights.items():
        z = zscore_series(out[col])
        component = 50 + 15 * z.clip(-3, 3)
        out[f"{col}_score"] = component
        score = score + weight * component

    out["extension_penalty"] = (
        out["price_change_7d"].clip(lower=0).fillna(0) * 100 * 0.35
    ).clip(upper=25)

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
