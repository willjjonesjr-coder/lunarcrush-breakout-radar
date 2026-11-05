"""Causal, single-pass historical features used only by the backtest.

The live scanner's scalar implementations in signals.py remain the reference.
"""

import numpy as np
import pandas as pd


FEATURE_COLUMNS = (
    "social_accel", "contributor_accel", "engagement_accel",
    "sentiment_change", "social_dominance_change", "volume_accel",
    "price_change_7d", "price_change_30d", "galaxy_score_change", "spam_change",
    "last_price", "last_time", "social_price_divergence",
)
EMA_COLUMNS = (
    "has_ema50", "has_ema100", "has_ema200", "distance_ema50",
    "distance_ema100", "distance_ema200", "ema_convergence", "ema50_slope_5d",
    "bullish_alignment", "near_ema50", "near_ema100", "near_ema200",
    "ema50_cross_recent",
)


def historical_features(hist):
    """Return features for each prefix ending at positions 9 through len(hist)-1.

    Rows retain ``hist.index[9:]``, including duplicate labels. Input order is
    preserved, not sorted: all windows count observations rather than dates.
    Each row matches feature_row(prefix) plus ema_features(prefix,
    require_200=False), using the latter's default 5% proximity and 10-period
    crossing window. When close is missing, EMA columns are omitted, matching the absent EMA
    dictionary in the legacy concatenated signal frame.
    Histories shorter than ten observations return an empty, fixed-schema frame.
    """
    if len(hist) < 10:
        return pd.DataFrame(index=hist.index[:0], columns=FEATURE_COLUMNS + EMA_COLUMNS)

    # Work on positional labels so duplicate/nonmonotonic source indexes never
    # trigger alignment or alter shift/rolling semantics.
    h = hist.reset_index(drop=True)
    out = pd.DataFrame(index=h.index)

    def numeric(column):
        if column not in h:
            return pd.Series(np.nan, index=h.index)
        return pd.to_numeric(h[column], errors="coerce")

    def acceleration(column):
        values = numeric(column)
        short = values.rolling(7, min_periods=3).mean()
        base = values.shift(7).rolling(23, min_periods=8).mean()
        return (short / base - 1.0).where(base.ne(0))

    def change(column, periods=7):
        values = numeric(column)
        base = values.shift(periods)
        return (values / base - 1.0).where(base.ne(0))

    for name, column in (
        ("social_accel", "posts_active"),
        ("contributor_accel", "contributors_active"),
        ("engagement_accel", "interactions"),
        ("volume_accel", "volume_24h"),
    ):
        out[name] = acceleration(column)
    for name, column, periods in (
        ("sentiment_change", "sentiment", 7),
        ("social_dominance_change", "social_dominance", 7),
        ("price_change_7d", "close", 7),
        ("price_change_30d", "close", 30),
        ("galaxy_score_change", "galaxy_score", 7),
        ("spam_change", "spam", 7),
    ):
        out[name] = change(column, periods)
    close = numeric("close")
    out["last_price"] = close
    out["last_time"] = h["time"]
    social = out[["social_accel", "contributor_accel", "engagement_accel"]]
    # numpy nanmean, as in feature_row, preserves +/-infinity behavior and the
    # same left-to-right sum; pandas' skipna mean can differ with infinities.
    values = social.to_numpy(dtype=float)
    count = np.sum(~np.isnan(values), axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        strength = np.nansum(values, axis=1) / count
    out["social_price_divergence"] = strength - out["price_change_7d"].clip(lower=0)

    if "close" in h:
        lengths = np.arange(1, len(h) + 1)
        emas = {}
        for span in (50, 100, 200):
            ema = close.ewm(span=span, adjust=False).mean()
            emas[span] = ema
            available = lengths >= span
            out[f"has_ema{span}"] = available
            distance = (close / ema - 1.0).where(available)
            out[f"distance_ema{span}"] = distance
            out[f"near_ema{span}"] = distance.abs().le(0.05)
        all_available = lengths >= 200
        ema_values = pd.DataFrame(emas)
        out["ema_convergence"] = (
            (ema_values.max(axis=1, skipna=False) - ema_values.min(axis=1, skipna=False)) / close
        ).where(all_available)
        out["ema50_slope_5d"] = (emas[50] / emas[50].shift(5) - 1.0).where(lengths >= 50)
        out["bullish_alignment"] = all_available & (emas[50] > emas[100]) & (emas[100] > emas[200])
        diff = emas[50] - emas[100]
        crosses = (diff.shift(1) <= 0) & (diff > 0)
        # A tail of 11 EMA values gives exactly 10 transitions. Detect before
        # availability masking, since the first eligible prefix may include a
        # cross that happened before the 100th observation.
        out["ema50_cross_recent"] = crosses.rolling(10, min_periods=1).max().eq(1) & (lengths >= 100)

    columns = FEATURE_COLUMNS + (EMA_COLUMNS if "close" in h else ())
    result = out.loc[:, columns].iloc[9:].copy()
    result.index = hist.index[9:]
    return result
