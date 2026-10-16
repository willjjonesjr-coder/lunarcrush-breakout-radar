#!/usr/bin/env python3
"""Point-in-time crypto market regime score (1 bearish, 100 bullish).

Inputs: daily UTC OHLCV files data_price/<lunarcrush_id>.csv and a verified
coin-ID mapping JSON with entries {"id":{"symbol":"BTC","name":"Bitcoin"}}.
No future observations enter a historical score. No interpolation or backfill
across missing dates. BTC and ETH must both be present.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

WEIGHTS = {"trend": .30, "breadth": .25, "momentum": .20,
           "participation": .15, "sentiment": .10}

def clamp(x):
    return float(np.clip(x, 1, 100))

def score_centered(value, scale):
    return clamp(50 + 40 * np.tanh(float(value) / scale))

def classify(score, strength):
    if 41 <= score <= 60:
        return "volatile sideways" if strength >= 60 else "consolidation"
    return ("extreme bearish" if score <= 15 else
            "strong bearish" if score <= 30 else
            "mild bearish" if score <= 40 else
            "mild bullish" if score <= 70 else
            "strong bullish" if score <= 85 else "extreme bullish")

def read_prices(folder, mapping):
    out = {}
    for cid, identity in mapping.items():
        path = Path(folder) / f"{cid}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        required = {"time", "close", "volume"}
        if not required.issubset(df.columns):
            continue
        df["time"] = pd.to_datetime(df.time, utc=True).dt.normalize()
        for col in ("close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["time", "close"]).sort_values("time").drop_duplicates("time", keep="last")
        df = df[df.close > 0].set_index("time")
        if not df.empty:
            out[cid] = (identity, df)
    return out

def features(df):
    # min_periods prevents immature EMAs from being counted as full-history signals.
    c = df.close
    f = pd.DataFrame(index=df.index)
    for n in (50, 100, 200):
        f[f"ema{n}"] = c.ewm(span=n, adjust=False, min_periods=n).mean()
    f["ret7"] = c / c.shift(7) - 1
    f["ret30"] = c / c.shift(30) - 1
    f["ret90"] = c / c.shift(90) - 1
    f["vol30"] = c.pct_change().rolling(30).std() * np.sqrt(30)
    f["volume_ratio"] = df.volume.rolling(7).mean() / df.volume.shift(7).rolling(30).mean()
    f["close"] = c
    return f

def regime(prices, social=None, min_breadth=10):
    by_symbol = {}
    all_features = {}
    for cid, (identity, df) in prices.items():
        symbol = str(identity.get("symbol", "")).upper()
        if symbol in by_symbol:
            # Ambiguous duplicate symbols must be explicitly resolved.
            raise ValueError(f"Duplicate symbol {symbol}: verify asset identity")
        by_symbol[symbol] = cid
        all_features[cid] = features(df)
    if "BTC" not in by_symbol or "ETH" not in by_symbol:
        raise ValueError("Verified BTC and ETH OHLCV histories are both required")
    btc, eth = all_features[by_symbol["BTC"]], all_features[by_symbol["ETH"]]
    # Intersection ensures identical observation dates for BTC and ETH.
    dates = btc.index.intersection(eth.index)
    rows = []
    for date in dates:
        b, e = btc.loc[date], eth.loc[date]
        if any(pd.isna(x) for x in (b.ema200, e.ema200, b.ret90, e.ret90)):
            continue
        bench = [b, e]
        trend_parts = []
        for x in bench:
            alignment = (int(x.close > x.ema50) + int(x.ema50 > x.ema100) + int(x.ema100 > x.ema200)) / 3
            trend_parts.append(100 * alignment)
        trend = float(np.mean(trend_parts))
        eligible = [f.loc[date] for f in all_features.values()
                    if date in f.index and pd.notna(f.loc[date, "ema200"])]
        if len(eligible) < min_breadth:
            continue
        breadth = 100 * np.mean([.5 * int(x.close > x.ema50) +
                                 .5 * int(x.close > x.ema200) for x in eligible])
        # Market-relative directional momentum; not a forecast or return proxy.
        momentum = np.mean([score_centered(.35*x.ret7 + .40*x.ret30 + .25*x.ret90,
                                           .15) for x in bench])
        participation = np.mean([score_centered(
            (x.volume_ratio - 1) * np.sign(x.ret30), .6)
            for x in bench if pd.notna(x.volume_ratio)])
        if not np.isfinite(participation):
            continue
        # No social data => renormalize observable weights, never assume neutral.
        components = {"trend": trend, "breadth": breadth, "momentum": momentum,
                      "participation": participation}
        if social is not None and date in social.index and pd.notna(social.loc[date]):
            components["sentiment"] = clamp(social.loc[date])
        weight_total = sum(WEIGHTS[k] for k in components)
        raw = sum(components[k] * WEIGHTS[k] for k in components) / weight_total
        rows.append({"time": date, "raw_score": raw, "trend": trend,
                     "breadth": breadth, "momentum": momentum,
                     "participation": participation,
                     "sentiment": components.get("sentiment", np.nan),
                     "breadth_assets": len(eligible),
                     "sentiment_available": "sentiment" in components,
                     "btc_close": b.close, "eth_close": e.close})
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["score"] = result.raw_score.rolling(3, min_periods=1).mean().round(1)
    # Strength is separate from direction: a strongly trending bear scores high strength.
    result["trend_strength"] = (2 * (result.score - 50).abs()).clip(0, 100).round(1)
    result["classification"] = [classify(s, t) for s, t in
                                zip(result.score, result.trend_strength)]
    result["change_7d"] = result.score - result.score.shift(7)
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", default="data_price")
    ap.add_argument("--mapping", default="config/market_regime_symbols.json")
    ap.add_argument("--social-csv", default=None,
                    help="Optional UTC daily CSV with time and sentiment_score (1-100)")
    ap.add_argument("--min-breadth", type=int, default=10)
    ap.add_argument("--output", default="reports/market_regime.csv")
    args = ap.parse_args()
    mapping = json.loads(Path(args.mapping).read_text())
    social = None
    if args.social_csv:
        s = pd.read_csv(args.social_csv)
        s["time"] = pd.to_datetime(s.time, utc=True).dt.normalize()
        social = pd.Series(pd.to_numeric(s.sentiment_score, errors="coerce").values,
                           index=s.time).sort_index()
    result = regime(read_prices(args.prices, mapping), social, args.min_breadth)
    if result.empty:
        raise SystemExit("Insufficient aligned histories: need BTC, ETH and breadth assets with >=200 bars")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(result.tail(1).to_string(index=False))
    print(f"Rows: {len(result)}; saved {args.output}")

if __name__ == "__main__":
    main()
