"""Conservative point-in-time evaluation of archived daily radar signals.

Archived reports are immutable signal snapshots. Never recompute old scores with
new normalization and never use future history to create past candidate universes.
Only score the days and IDs actually recorded. Missing outcomes remain missing.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ARCHIVE = Path("reports/archive")
DATA = Path("data")
OUT = Path("reports")
files = sorted(ARCHIVE.glob("breakout_radar_????-??-??.csv"))
if not files:
    raise RuntimeError("No archived daily radar CSVs")

histories = {}
for path in DATA.glob("history_*.csv"):
    cid = path.stem.removeprefix("history_")
    h = pd.read_csv(path, usecols=lambda c: c in ("time", "close"))
    if not {"time", "close"}.issubset(h):
        continue
    h["date"] = pd.to_datetime(h.time, utc=True).dt.normalize()
    h["close"] = pd.to_numeric(h.close, errors="coerce")
    histories[cid] = h.dropna().sort_values("date").drop_duplicates("date", keep="last").set_index("date").close

def ret(cid, start, end):
    h = histories.get(str(cid))
    if h is None or start not in h.index or end not in h.index:
        return np.nan
    a, b = h.loc[start], h.loc[end]
    return float(b/a-1) if np.isfinite(a) and a > 0 and np.isfinite(b) and b >= 0 else np.nan

universe = pd.read_csv(DATA/"universe_latest.csv", dtype={"id":str})
symbols = universe.drop_duplicates("id").set_index("id").symbol.to_dict()
benchmarks = {sym: next((cid for cid, s in symbols.items()
                          if str(s).upper() == sym and cid in histories), None)
              for sym in ("BTC", "ETH")}
observations = []
coverage = []
for path in files:
    date = pd.Timestamp(path.stem.removeprefix("breakout_radar_"), tz="UTC")
    snap = pd.read_csv(path, dtype={"id":str})
    if not {"id","breakout_score","stage"}.issubset(snap):
        continue
    snap = snap.drop_duplicates("id")
    coverage.append({"date":str(date.date()),"archived_candidates":len(snap),
                     "normalization":str(snap.normalization_version.iloc[0])
                     if "normalization_version" in snap else "legacy_run_relative"})
    for row in snap.itertuples(index=False):
        for horizon in (7,14):
            end = date + pd.Timedelta(days=horizon)
            result = ret(row.id,date,end)
            reasons = []
            if not np.isfinite(result):
                reasons.append("MISSING_OUTCOME")
            elif result > 10:
                reasons.append("EXTREME_GAIN_GT_1000PCT")
            elif result < -1:
                reasons.append("INVALID_LOSS")
            category = getattr(row,"asset_type","unverified")
            if category != "unverified":
                reasons.append("NON_ALTCOIN_CATEGORY")
            btc = ret(benchmarks["BTC"],date,end) if benchmarks["BTC"] else np.nan
            eth = ret(benchmarks["ETH"],date,end) if benchmarks["ETH"] else np.nan
            observations.append({
                "signal_date":str(date.date()),"id":row.id,"symbol":row.symbol,
                "score":float(row.breakout_score),"stage":row.stage,
                "normalization":getattr(row,"normalization_version","legacy_run_relative"),
                "asset_type":category,"horizon_days":horizon,
                "forward_return":result,"btc_return":btc,"eth_return":eth,
                "excess_btc":result-btc,"excess_eth":result-eth,
                "quality_flags":"|".join(reasons),"eligible":not reasons})
obs = pd.DataFrame(observations)
obs.to_csv(OUT/"walkforward_observations.csv",index=False)
eligible = obs[obs.eligible].copy()
def summary(frame,keys):
    results=[]
    for values,g in frame.groupby(keys,observed=True):
        if not isinstance(values,tuple):values=(values,)
        item=dict(zip(keys,values))
        item.update(n=len(g),days=int(g.signal_date.nunique()),assets=int(g.id.nunique()),
                    median_return=float(g.forward_return.median()),
                    win_rate=float((g.forward_return>0).mean()),
                    median_excess_btc=float(g.excess_btc.median()) if g.excess_btc.notna().any() else None,
                    median_excess_eth=float(g.excess_eth.median()) if g.excess_eth.notna().any() else None)
        results.append(item)
    return results
report={
    "archive_days":len(coverage),"archive_coverage":coverage,
    "observations":len(obs),"eligible":len(eligible),
    "missing_outcomes":int(obs.quality_flags.str.contains("MISSING_OUTCOME").sum()),
    "benchmark_ids":benchmarks,
    "by_horizon_and_stage":summary(eligible,["horizon_days","stage"]),
    "by_horizon_and_normalization":summary(eligible,["horizon_days","normalization"]),
    "by_horizon_and_signal_date":summary(eligible,["horizon_days","signal_date"]),
    "limitations":[
        "Only archived finalist/qualifying signals are observed; no full point-in-time universe.",
        "Archived legacy and fixed scores are NOT directly comparable.",
        "Historical files may omit delisted coins; outcome coverage is incomplete.",
        "Repeated assets and overlapping holding windows violate independence.",
        "No investable portfolio, slippage, fees, or position sizing modeled.",
        "Later archives may lack 7/14 days of realized outcomes; they remain missing.",
        "Not an out-of-sample test of a frozen strategy; exploratory evaluation only."
    ]
}
(OUT/"walkforward_summary.json").write_text(json.dumps(report,indent=2,default=str))
print(json.dumps({k:report[k] for k in ("archive_days","observations","eligible","missing_outcomes","benchmark_ids")},indent=2))
