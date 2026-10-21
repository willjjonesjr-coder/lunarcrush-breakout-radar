import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from production_regime import clean_history, refresh_prices, evaluate, attach_context

NOW=pd.Timestamp('2026-10-21T23:00:00Z')


def frame():
    dates=pd.date_range(end=NOW.normalize()-pd.Timedelta(days=1),periods=300,freq='D')
    return pd.DataFrame({'time':dates,'close':np.linspace(100,200,300),'volume':np.linspace(1000,2000,300)})


def cfg():
    return {'exchange':'kraken','bars':500,'minimum_contiguous_days':230,
            'minimum_assets':3,'minimum_coverage':0.7,'pairs':{'BTC':'BTC/USD','ETH':'ETH/USD','SOL':'SOL/USD'}}


def prices():
    h=clean_history(frame(),NOW)
    return {s:({'symbol':s},h.copy()) for s in cfg()['pairs']}


class ProductionRegimeTests(unittest.TestCase):
    def test_existing_model_produces_fresh_regime(self):
        summary,result=evaluate(prices(),cfg(),NOW)
        self.assertEqual(summary['status'],'AVAILABLE')
        self.assertEqual(summary['as_of'],'2026-10-20T00:00:00+00:00')
        self.assertGreater(summary['score'],60)
        self.assertFalse(summary['sentiment_available'])
        self.assertEqual(summary['available_assets'],3)

    def test_stale_benchmark_rejected_at_cleaning(self):
        with self.assertRaisesRegex(ValueError,'latest complete'):
            clean_history(frame().iloc[:-1],NOW)

    def test_gap_cannot_be_compressed(self):
        h=frame();h=h.drop(index=280)
        with self.assertRaisesRegex(ValueError,'contiguous'):
            clean_history(h,NOW)

    def test_invalid_volume_causes_gap_not_neutral_observation(self):
        h=frame();h.loc[280,'volume']=np.inf
        with self.assertRaises(ValueError):clean_history(h,NOW)

    def test_partial_future_day_excluded(self):
        h=frame();extra=h.tail(1).copy();extra['time']=NOW.normalize();extra['close']=1e9
        out=clean_history(pd.concat([h,extra]),NOW)
        self.assertEqual(out.close.iloc[-1],200)

    def test_missing_btc_not_replaced_by_altcoin(self):
        p=prices();del p['BTC']
        out,_=evaluate(p,cfg(),NOW)
        self.assertEqual(out['status'],'UNAVAILABLE')
        self.assertIsNone(out['score'])

    def test_inadequate_coverage_not_published_as_bear(self):
        c=cfg();c['pairs'].update({'XRP':'XRP/USD','ADA':'ADA/USD'})
        out,_=evaluate(prices(),c,NOW)
        self.assertEqual(out['status'],'UNAVAILABLE')
        self.assertIsNone(out['score'])

    def test_outage_can_replace_previous_context_with_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'breakout_radar.json'
            p.write_text('[{"id":1,"breakout_score":75,"market_regime_score":90}]')
            summary,_=evaluate({},cfg(),NOW)
            attach_context(tmp,summary)
            row=json.loads(p.read_text())[0]
            self.assertEqual(row['breakout_score'],75)
            self.assertIsNone(row['market_regime_score'])
            self.assertEqual(row['market_regime_status'],'UNAVAILABLE')

    def test_coverage_basket_is_independent_of_radar_files(self):
        class Exchange:
            def __init__(self,opts):
                self.markets={p:{'base':s,'quote':'USD','spot':True} for s,p in cfg()['pairs'].items()}
            def load_markets(self):pass
            def fetch_ohlcv(self,pair,**kwargs):
                h=frame()
                return [[int(r.time.timestamp()*1000),r.close,r.close,r.close,r.close,r.volume] for r in h.itertuples()]
        with tempfile.TemporaryDirectory() as tmp:
            p,inventory=refresh_prices(cfg(),tmp,NOW,Exchange)
            self.assertEqual(set(p),{'BTC','ETH','SOL'})
            self.assertTrue(all(r['status']=='fresh' for r in inventory))
            def no_network(opts):raise AssertionError('cache should avoid network')
            cached,inventory=refresh_prices(cfg(),tmp,NOW,no_network)
            self.assertEqual(len(cached),3)
            self.assertTrue(all(r['status']=='cached' for r in inventory))

    def test_pair_identity_must_match_explicit_configuration(self):
        class Wrong:
            def __init__(self,opts):self.markets={'BTC/USD':{'base':'OTHER','quote':'USD','spot':True}}
            def load_markets(self):pass
            def fetch_ohlcv(self,*a,**kw):raise AssertionError('wrong pair must not fetch')
        with tempfile.TemporaryDirectory() as tmp:
            p,inventory=refresh_prices(cfg(),tmp,NOW,Wrong)
            self.assertEqual(p,{})
            self.assertTrue(all(r['status']=='unavailable' for r in inventory))


if __name__=='__main__':unittest.main()
