"""Auditable quality screening and matched benchmark summaries for historical replay."""
import json
from pathlib import Path
import pandas as pd
import numpy as np

REPORTS = Path("reports")
DATA = Path("data")
raw = pd.read_csv(REPORTS / "historical_forward_returns.csv", dtype={"id": str})
if raw.empty:
    raise RuntimeError("Historical replay contains no observations")
raw["cutoff_utc"] = pd.to_datetime(raw["cutoff_utc"], utc=True)
raw["date0"] = raw["cutoff_utc"].dt.normalize()
raw["date1"] = raw["date0"] + pd.to_timedelta(raw["horizon_days"], unit="D")
raw["forward_return"] = pd.to_numeric(raw["forward_return"], errors="coerce")
raw["quality_flags"] = ""
raw.loc[raw.forward_return > 10, "quality_flags"] += "EXTREME_GAIN_GT_1000PCT|"
raw.loc[raw.forward_return < -1, "quality_flags"] += "RETURN_BELOW_MINUS_100PCT|"
raw.loc[~np.isfinite(raw.forward_return), "quality_flags"] += "NONFINITE_RETURN|"
raw.loc[raw.asset_type.ne("unverified"), "quality_flags"] += "NON_ALTCOIN_ASSET_TYPE|"

# Offline daily price data: exact UTC calendar matching, no API calls.
prices = {}
for file in DATA.glob("history_*.csv"):
    coin_id = file.stem.removeprefix("history_")
    h = pd.read_csv(file, usecols=lambda c: c in ("time", "close"))
    if not {"time", "close"}.issubset(h.columns):
        continue
    h["date"] = pd.to_datetime(h["time"], utc=True).dt.normalize()
    h["close"] = pd.to_numeric(h["close"], errors="coerce")
    prices[coin_id] = h.dropna().sort_values("date").drop_duplicates("date", keep="last").set_index("date")["close"]

def matched_return(coin_id, start, end):
    series = prices.get(str(coin_id))
    if series is None or start not in series.index or end not in series.index:
        return np.nan
    p0, p1 = series.loc[start], series.loc[end]
    return float(p1 / p0 - 1) if np.isfinite(p0) and p0 > 0 and np.isfinite(p1) and p1 > 0 else np.nan

# BTC and ETH IDs must be verified against historical file contents.
# If ID is absent or mismatched, benchmark is unavailable rather than fabricated.
universe = pd.read_csv(DATA / "universe_latest.csv", dtype={"id": str})
symbols = universe.drop_duplicates("id").set_index("id")["symbol"].to_dict()
benchmark_ids = {}
for ticker in ("BTC", "ETH"):
    matches = [coin_id for coin_id, symbol in symbols.items()
               if str(symbol).upper() == ticker and coin_id in prices]
    benchmark_ids[ticker] = matches[0] if len(matches) == 1 else None

# Precompute exact-date universe cross-sectional MEDIAN returns.
# This is a survivor-biased descriptive baseline, not an investable index.
date_pairs = raw[["date0", "date1"]].drop_duplicates()
universe_baseline = {}
for row in date_pairs.itertuples(index=False):
    vals = [matched_return(cid, row.date0, row.date1) for cid in prices]
    vals = [v for v in vals if np.isfinite(v) and -1 <= v <= 10]
    universe_baseline[(row.date0, row.date1)] = float(np.median(vals)) if vals else np.nan

for ticker, cid in benchmark_ids.items():
    raw[ticker.lower() + "_return"] = [
        matched_return(cid, start, end) if cid else np.nan
        for start, end in zip(raw.date0, raw.date1)]
raw["universe_median_return"] = [
    universe_baseline[(start, end)] for start, end in zip(raw.date0, raw.date1)]
for benchmark in ("btc", "eth"):
    raw["excess_vs_" + benchmark] = raw.forward_return - raw[benchmark + "_return"]
raw["excess_vs_universe"] = raw.forward_return - raw.universe_median_return

# Check that the original replay horizon represents actual elapsed calendar days.
for index, row in raw.iterrows():
    series = prices.get(row["id"])
    if series is None or row.date0 not in series.index or row.date1 not in series.index:
        raw.at[index, "quality_flags"] += "MISSING_EXACT_HORIZON_PRICE|"
    else:
        actual = matched_return(row["id"], row.date0, row.date1)
        if not np.isfinite(actual) or not np.isclose(actual, row.forward_return, rtol=1e-7, atol=1e-9):
            raw.at[index, "quality_flags"] += "HORIZON_PRICE_MISMATCH|"

raw["quality_flags"] = raw.quality_flags.str.rstrip("|")
raw["qc_eligible"] = raw.quality_flags.eq("")
raw.to_csv(REPORTS / "historical_forward_returns_audited.csv", index=False)
raw.loc[~raw.qc_eligible].to_csv(REPORTS / "historical_quality_flags.csv", index=False)

def grouped(df, keys):
    output = []
    for labels, group in df.groupby(keys, observed=True):
        if not isinstance(labels, tuple):
            labels = (labels,)
        record = {key: (int(val) if key == "horizon_days" else str(val))
                  for key, val in zip(keys, labels)}
        record.update(n=len(group), unique_assets=int(group.id.nunique()),
                      median_return=float(group.forward_return.median()),
                      mean_return=float(group.forward_return.mean()),
                      positive_rate=float((group.forward_return > 0).mean()))
        for bench in ("btc", "eth", "universe"):
            vals = group["excess_vs_" + bench].dropna()
            record[bench + "_matched_n"] = len(vals)
            record["median_excess_vs_" + bench] = float(vals.median()) if len(vals) else None
        output.append(record)
    return output

eligible = raw.loc[raw.qc_eligible].copy()
eligible["score_band"] = pd.cut(eligible.score, [-1, 45, 55, 65, 75, 101],
                                labels=["<45", "45-54", "55-64", "65-74", "75+"])
summary = {
    "total": len(raw), "quality_flagged": int((~raw.qc_eligible).sum()),
    "eligible": len(eligible), "benchmark_coin_ids": benchmark_ids,
    "quality_flags": raw.loc[~raw.qc_eligible, "quality_flags"].value_counts().to_dict(),
    "score": grouped(eligible, ["horizon_days", "score_band"]),
    "stage": grouped(eligible, ["horizon_days", "stage"]),
    "asset_type": grouped(raw.loc[raw.quality_flags.str.contains("NON_ALTCOIN_ASSET_TYPE")],
                          ["horizon_days", "asset_type"]),
    "caveats": [
        "Extreme gains over 1000% are flagged, not deleted; threshold is heuristic.",
        "Asset classification is incomplete; unverified does not mean verified altcoin.",
        "Current-universe selection creates survivorship bias.",
        "Universe baseline is cross-sectional median, not equal-weight portfolio return.",
        "Overlapping horizons, no trading fees, liquidity or execution modeling.",
        "No true out-of-sample or multi-regime validation yet."
    ]
}
(REPORTS / "audited_backtest_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps({k: summary[k] for k in ("total","quality_flagged","eligible","benchmark_coin_ids","quality_flags")}, indent=2))
