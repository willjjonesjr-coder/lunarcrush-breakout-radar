#!/usr/bin/env python3
"""Join backtest signals with point-in-time regime and BTC/ETH benchmark returns.

Benchmark is 50/50 equal-weight buy-and-hold *at each signal date*, with
horizon endpoints aligned to exact UTC calendar days. Missing values stay NA.
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

HORIZONS=(7,14,30)

def load_prices(path):
    df=pd.read_csv(path)
    df["date"]=pd.to_datetime(df["time"],utc=True).dt.normalize()
    df["close"]=pd.to_numeric(df["close"],errors="coerce")
    return df.drop_duplicates("date").set_index("date")["close"].sort_index()

def benchmark_returns(folder, dates, horizons=HORIZONS):
    btc=load_prices(Path(folder)/"btc.csv")
    eth=load_prices(Path(folder)/"eth.csv")
    rows=[]
    for date in dates:
        row={"date":date}
        for h in horizons:
            end=date+pd.Timedelta(days=h)
            if all(t in series.index for series in (btc,eth) for t in (date,end)):
                b0,b1=btc.loc[date],btc.loc[end]
                e0,e1=eth.loc[date],eth.loc[end]
                row[f"benchmark_return_{h}d"]=float(.5*(b1/b0-1)+.5*(e1/e0-1)) if b0>0 and e0>0 else np.nan
            else:
                row[f"benchmark_return_{h}d"]=np.nan
        rows.append(row)
    return pd.DataFrame(rows)

def attach(signals, regime, folder):
    signals=signals.copy()
    signals["date"]=pd.to_datetime(signals["time"],utc=True).dt.normalize()
    regime=regime.copy()
    regime["date"]=pd.to_datetime(regime["time"],utc=True).dt.normalize()
    regime=regime.drop_duplicates("date")
    cols=["date","score","change_7d","classification","breadth_assets","sentiment_available"]
    joined=signals.merge(regime[cols].rename(columns={"score":"regime_score",
                 "change_7d":"regime_change_7d","classification":"regime_classification"}),
                 on="date",how="left",validate="many_to_one")
    joined=joined.merge(benchmark_returns(folder,joined.date.drop_duplicates().tolist()),
                        on="date",how="left",validate="many_to_one")
    h=pd.to_numeric(joined["horizon_days"],errors="coerce")
    joined["benchmark_return"]=np.nan
    for horizon in HORIZONS:
        mask=h==horizon
        joined.loc[mask,"benchmark_return"]=joined.loc[mask,f"benchmark_return_{horizon}d"]
    joined["excess_return"]=pd.to_numeric(joined["forward_return"],errors="coerce")-joined["benchmark_return"]
    joined["beat_benchmark"]=np.where(joined["excess_return"].notna(),joined["excess_return"]>0,np.nan)
    joined["regime_band"]=pd.cut(joined.regime_score,bins=[0,40,60,100],
                                  labels=["bearish_1_40","consolidation_41_60","bullish_61_100"])
    joined["regime_direction"]=np.select(
        [joined.regime_change_7d>2,joined.regime_change_7d< -2],
        ["rising","falling"],default="flat_or_unknown")
    return joined.drop(columns=["date"])

def summarize(joined):
    valid=joined.dropna(subset=["regime_score","benchmark_return","excess_return"])
    if valid.empty:
        return pd.DataFrame(columns=["strategy","threshold","horizon_days","regime_band",
             "regime_direction","signals","mean_return","mean_benchmark","mean_excess",
             "benchmark_win_rate","positive_return_rate"])
    # Signal rows repeat across score thresholds in the source backtest; group
    # on strategy/horizon and regime to avoid confusing threshold overlap.
    rows=[]
    for keys,grp in valid.groupby(["strategy","horizon_days","regime_band","regime_direction"],
                                   observed=True,dropna=False):
        rows.append(dict(zip(["strategy","horizon_days","regime_band","regime_direction"],keys),
                         signals=len(grp),unique_signal_dates=grp["time"].nunique(),
                         mean_return=grp.forward_return.mean(),
                         mean_benchmark=grp.benchmark_return.mean(),
                         mean_excess=grp.excess_return.mean(),
                         benchmark_win_rate=grp.beat_benchmark.mean(),
                         positive_return_rate=(grp.forward_return>0).mean()))
    return pd.DataFrame(rows)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--signals",default="reports/backtest_per_coin.csv")
    p.add_argument("--regime",default="reports/market_breadth_provisional.csv")
    p.add_argument("--prices",default="data_price")
    p.add_argument("--output",default="reports/backtest_regime_signals.csv")
    p.add_argument("--summary",default="reports/backtest_regime_summary.csv")
    a=p.parse_args()
    joined=attach(pd.read_csv(a.signals),pd.read_csv(a.regime),a.prices)
    summary=summarize(joined)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    joined.to_csv(a.output,index=False)
    summary.to_csv(a.summary,index=False)
    print(f"Signal rows: {len(joined)}; regime matched: {joined.regime_score.notna().sum()}; benchmark matched: {joined.benchmark_return.notna().sum()}")
    print(summary.to_string(index=False))
if __name__=="__main__":
    main()
