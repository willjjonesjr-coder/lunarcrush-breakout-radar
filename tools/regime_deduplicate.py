#!/usr/bin/env python3
"""Deduplicated regime backtest: one event per coin/day/horizon/strategy.

Thresholds are nested views of the same event, not independent trades.
Reports include date-clustered statistics, medians, and outlier sensitivity.
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

KEY=["coin_id","time","horizon_days","strategy"]
GROUP=["strategy","horizon_days","regime_band","regime_direction"]

def deduplicate(df):
    df=df.copy()
    df["time"]=pd.to_datetime(df.time,utc=True).dt.normalize()
    df["breakout_score"]=pd.to_numeric(df.breakout_score,errors="coerce")
    df["threshold"]=pd.to_numeric(df.get("threshold",np.nan),errors="coerce")
    # Retain highest breakout-score representation; identical event outcomes
    # must agree across threshold views. Raise rather than silently mask conflicts.
    for col in ["forward_return","benchmark_return","excess_return","regime_score"]:
        disagreement=df.groupby(KEY,dropna=False)[col].agg(
            lambda s: s.dropna().max()-s.dropna().min() if s.notna().any() else 0)
        if (disagreement>1e-8).any():
            raise ValueError(f"Conflicting duplicate event values: {col}")
    df=df.sort_values(["breakout_score","threshold"],ascending=[False,False],kind="stable")
    return df.drop_duplicates(KEY,keep="first").sort_values(KEY).reset_index(drop=True)

def report(df):
    valid=df.dropna(subset=["regime_score","benchmark_return","excess_return"]).copy()
    valid["date"]=valid.time.dt.normalize()
    rows=[]
    for keys,g in valid.groupby(GROUP,observed=True,dropna=False):
        # Date-balanced average prevents days with more coin signals from
        # dominating estimates. This is descriptive, not a significance test.
        daily=g.groupby("date").excess_return.mean()
        trimmed=g.excess_return.sort_values()
        remove=max(1,int(np.ceil(.01*len(trimmed))))
        without_top=trimmed.iloc[:-remove] if len(trimmed)>remove else trimmed.iloc[:0]
        monthly=g.groupby(g.date.dt.to_period("M").astype(str)).excess_return.mean()
        rows.append(dict(zip(GROUP,keys),
            unique_events=len(g),unique_coins=g.coin_id.nunique(),
            unique_dates=g.date.nunique(),unique_months=len(monthly),
            mean_return=g.forward_return.mean(),median_return=g.forward_return.median(),
            mean_excess=g.excess_return.mean(),median_excess=g.excess_return.median(),
            date_balanced_mean_excess=daily.mean(),
            month_median_excess=monthly.median(),
            benchmark_win_rate=(g.excess_return>0).mean(),
            positive_return_rate=(g.forward_return>0).mean(),
            mean_excess_excluding_top_1pct=without_top.mean(),
            mean_excess_excluding_best_coin=g.loc[g.coin_id!=g.groupby("coin_id").excess_return.mean().idxmax(),"excess_return"].mean()))
    return pd.DataFrame(rows)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",default="reports/backtest_regime_signals.csv")
    p.add_argument("--events",default="reports/backtest_regime_deduplicated.csv")
    p.add_argument("--summary",default="reports/backtest_regime_robustness.csv")
    a=p.parse_args()
    raw=pd.read_csv(a.input,low_memory=False)
    unique=deduplicate(raw)
    result=report(unique)
    Path(a.events).parent.mkdir(parents=True,exist_ok=True)
    unique.to_csv(a.events,index=False)
    result.to_csv(a.summary,index=False)
    print(f"Raw rows: {len(raw)}; unique coin/day/horizon/strategy events: {len(unique)}")
    print(f"Unique coin/day/horizon events across strategies: {unique.drop_duplicates(['coin_id','time','horizon_days']).shape[0]}")
    print(result.to_string(index=False))
if __name__=="__main__":
    main()
