import unittest
import numpy as np
import pandas as pd
from scanner import snapshot_filter,feature_row,score_candidates
from test_radar_quality import history,NOW

CFG={'universe':{'min_market_cap':250e6,'max_market_cap':10e9,'min_volume_24h':10e6,
                 'max_7d_price_change':35,'exclude_symbols':['USDT']}}


class FilterLabelTests(unittest.TestCase):
    def test_reference_breaches_and_missing_values_remain_visible(self):
        rows=[]
        for symbol,cap,vol,gain in [('SMALL',1e6,1000,100),('BIG',100e9,20e6,5),
                                   ('UNKNOWN',np.nan,np.nan,np.nan),('USDT',1e9,10e6,0)]:
            rows.append({'symbol':symbol,'market_cap':cap,'volume_24h':vol,'percent_change_7d':gain,
                         'social_volume_24h':10,'interactions_24h':10,'social_dominance':1,
                         'sentiment':50,'galaxy_score':50})
        out=snapshot_filter(pd.DataFrame(rows),CFG).set_index('symbol')
        self.assertEqual(set(out.index),{'SMALL','BIG','UNKNOWN'})
        self.assertEqual(out.loc['SMALL','price_extension_label'],'ABOVE 7D GAIN REFERENCE')
        self.assertEqual(out.loc['SMALL','liquidity_label'],'BELOW VOLUME REFERENCE')
        self.assertEqual(out.loc['BIG','market_cap_label'],'ABOVE MAX MARKET-CAP REFERENCE')
        self.assertEqual(out.loc['UNKNOWN','market_cap_label'],'UNKNOWN')

    def test_history_gaps_are_labels_when_math_remains_available(self):
        h=history()
        h.loc[h.time==pd.Timestamp('2026-10-03T00:00Z'),'posts_active']=np.nan
        features=feature_row(h,NOW)
        self.assertFalse(features['history_complete_30d'])
        out=score_candidates(pd.DataFrame([features]),{}).iloc[0]
        self.assertEqual(out.data_status,'PARTIAL HISTORY')
        self.assertTrue(np.isfinite(out.breakout_score))

    def test_missing_scoring_inputs_remain_unscored(self):
        f=feature_row(history(),NOW);f['last_price']=np.nan
        out=score_candidates(pd.DataFrame([f]),{}).iloc[0]
        self.assertEqual(out.stage,'INSUFFICIENT DATA')
        self.assertTrue(pd.isna(out.breakout_score))


if __name__=='__main__':unittest.main()
