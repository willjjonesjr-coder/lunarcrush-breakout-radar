"""Refresh an explicit independent market basket and publish the existing regime model."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from market_regime import regime


def utc_now():
    return pd.Timestamp.now(tz='UTC')


def clean_history(frame, as_of, minimum=230, bars=500):
    """Use only the gap-free suffix ending at the latest complete UTC day."""
    expected = pd.Timestamp(as_of).tz_convert('UTC').normalize()-pd.Timedelta(days=1)
    if not {'time','close','volume'}.issubset(frame.columns):
        raise ValueError('missing time/close/volume columns')
    h=frame.copy()
    h['time']=pd.to_datetime(h.time,utc=True,errors='coerce')
    for col in ['close','volume']:
        h[col]=pd.to_numeric(h[col],errors='coerce')
    h=h[np.isfinite(h.close)&(h.close>0)&np.isfinite(h.volume)&(h.volume>=0)]
    h=h.dropna(subset=['time']).sort_values('time',kind='stable').drop_duplicates('time',keep='last')
    h=h[(h.time<=expected)&(h.time==h.time.dt.normalize())].set_index('time')
    if h.empty or h.index.max()!=expected:
        raise ValueError('latest complete UTC day unavailable')
    gap=h.index.to_series().diff().gt(pd.Timedelta(days=1))
    if gap.any():h=h.loc[gap[gap].index[-1]:]
    h=h.tail(bars)
    if len(h)<minimum:
        raise ValueError(f'insufficient contiguous history ({len(h)}/{minimum})')
    return h[['close','volume']]


def refresh_prices(cfg, folder, as_of, exchange_factory=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    prices={};inventory=[];client=None;load_error=None;started=time.monotonic()
    for symbol,pair in cfg['pairs'].items():
        path=folder/(symbol+'.csv')
        entry={'symbol':symbol,'pair':pair,'exchange':cfg['exchange'],'status':'unavailable'}
        try:
            if path.exists():
                cached=clean_history(pd.read_csv(path),as_of,cfg['minimum_contiguous_days'],cfg['bars'])
                prices[symbol]=({'symbol':symbol,'source':cfg['exchange'],'pair':pair},cached)
                entry.update(status='cached',bars=len(cached),last_day=cached.index.max().isoformat())
                inventory.append(entry);continue
        except (ValueError,OSError,pd.errors.EmptyDataError):
            pass
        try:
            if time.monotonic()-started>300:raise ValueError('refresh time budget exhausted')
            if load_error:raise ValueError('exchange unavailable: '+load_error)
            if client is None:
                try:
                    if exchange_factory is None:
                        import ccxt
                        exchange_factory=getattr(ccxt,cfg['exchange'])
                    client=exchange_factory({'enableRateLimit':True,'timeout':10000})
                    client.load_markets()
                except Exception as exc:
                    load_error=type(exc).__name__
                    raise ValueError('exchange unavailable: '+load_error) from exc
            market=client.markets.get(pair)
            if not market or market.get('base')!=symbol or market.get('quote')!='USD' or not market.get('spot',False):
                raise ValueError('configured spot pair/base/quote not confirmed')
            cutoff=int(pd.Timestamp(as_of).normalize().timestamp()*1000)
            candles=client.fetch_ohlcv(pair,timeframe='1d',since=cutoff-(cfg['bars']+20)*86400000,limit=720)
            fresh=pd.DataFrame(candles,columns=['timestamp','open','high','low','close','volume'])
            fresh['time']=pd.to_datetime(fresh.timestamp,unit='ms',utc=True)
            valid=clean_history(fresh,as_of,cfg['minimum_contiguous_days'],cfg['bars'])
            valid.reset_index().to_csv(path,index=False)
            prices[symbol]=({'symbol':symbol,'source':cfg['exchange'],'pair':pair},valid)
            entry.update(status='fresh',bars=len(valid),last_day=valid.index.max().isoformat())
        except Exception as exc:
            entry['reason']=type(exc).__name__+(': '+str(exc) if isinstance(exc,ValueError) else '')
        inventory.append(entry)
    return prices,inventory


def evaluate(prices,cfg,as_of):
    expected=pd.Timestamp(as_of).tz_convert('UTC').normalize()-pd.Timedelta(days=1)
    summary={'status':'UNAVAILABLE','as_of':None,'expected_day':expected.isoformat(),
             'observed_at':pd.Timestamp(as_of).isoformat(),'score':None,'classification':'unavailable',
             'trend_strength':None,'change_7d':None,'expected_assets':len(cfg['pairs']),
             'available_assets':len(prices),'coverage':len(prices)/len(cfg['pairs']),
             'source':cfg['exchange'],'model':'market_regime.py','sentiment_available':False,
             'usage':'context only; candidate scores and eligibility unchanged'}
    if not {'BTC','ETH'}.issubset(prices):
        summary['reason']='BTC and ETH are both required';return summary,pd.DataFrame()
    if len(prices)<cfg['minimum_assets'] or summary['coverage']<cfg['minimum_coverage']:
        summary['reason']='insufficient independent basket coverage';return summary,pd.DataFrame()
    result=regime(prices,min_breadth=cfg['minimum_assets'])
    if result.empty or pd.Timestamp(result.iloc[-1].time)!=expected:
        summary['reason']='no regime observation on latest complete day';return summary,result
    latest=result.iloc[-1]
    summary.update(status='AVAILABLE',as_of=latest.time.isoformat(),score=float(latest.score),
                   classification=str(latest.classification),trend_strength=float(latest.trend_strength),
                   change_7d=float(latest.change_7d) if pd.notna(latest.change_7d) else None,
                   breadth_assets=int(latest.breadth_assets),
                   components={k:float(latest[k]) for k in ['trend','breadth','momentum','participation']})
    return summary,result


def attach_context(reports,summary):
    columns={f'market_regime_{key}':summary.get(key) for key in
             ['status','as_of','score','classification','trend_strength','change_7d','coverage']}
    for stem in ['breakout_radar','radar_candidates','separated_assets']:
        path=Path(reports)/(stem+'.json')
        if not path.exists():continue
        rows=json.loads(path.read_text())
        for row in rows:row.update(columns)
        path.write_text(json.dumps(rows,allow_nan=False))
        if rows:pd.DataFrame(rows).to_csv(path.with_suffix('.csv'),index=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='config/production_regime.json')
    parser.add_argument('--reports-dir',default='reports')
    parser.add_argument('--prices-dir',default='data/market_regime_prices')
    args=parser.parse_args()
    cfg=json.loads(Path(args.config).read_text());as_of=utc_now();reports=Path(args.reports_dir)
    reports.mkdir(parents=True,exist_ok=True)
    prices,inventory=refresh_prices(cfg,args.prices_dir,as_of)
    summary,result=evaluate(prices,cfg,as_of)
    pd.DataFrame(inventory).to_csv(reports/'market_regime_inventory.csv',index=False)
    # Always replace previous outputs, including when the current reading is unavailable.
    if result.empty:result=pd.DataFrame(columns=['time','score','classification'])
    result.to_csv(reports/'market_regime.csv',index=False)
    (reports/'market_regime_latest.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
    attach_context(reports,summary)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
