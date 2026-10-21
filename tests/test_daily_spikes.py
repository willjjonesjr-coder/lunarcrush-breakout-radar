import unittest
import numpy as np
import pandas as pd

from daily_spikes import classify_spike, daily_comparisons
from scanner import feature_row, score_candidates
from test_radar_quality import history, NOW


class DailySpikeTests(unittest.TestCase):
    def test_each_day_excludes_itself_from_baseline(self):
        h = history()
        h['volume_24h'] = 100
        h['interactions'] = 1000
        date = pd.Timestamp('2026-10-20T00:00Z')
        h.loc[h.time == date, 'volume_24h'] = 400
        h.loc[h.time == date, 'interactions'] = 3000
        r = daily_comparisons(h, NOW).iloc[-1]
        self.assertEqual(r.volume_prior_7d_avg, 100)
        self.assertEqual(r.volume_spike_multiple, 4)
        self.assertEqual(r.volume_daily_accel, 3)
        self.assertEqual(r.engagement_daily_accel, 2)
        self.assertEqual(classify_spike(r), 'VOLUME + ENGAGEMENT')

    def test_every_historical_day_gets_its_own_baseline(self):
        h = history()
        h['volume_24h'] = np.arange(len(h))+1
        result = daily_comparisons(h, NOW)
        for index in range(7, len(result)):
            expected = h.volume_24h.iloc[index-7:index].mean()
            self.assertEqual(result.volume_prior_7d_avg.iloc[index], expected)
        self.assertTrue(result.volume_daily_accel.iloc[:7].isna().all())

    def test_gap_invalidates_seven_day_baseline(self):
        h = history();h = h[h.time != pd.Timestamp('2026-10-17T00:00Z')]
        r = daily_comparisons(h, NOW).iloc[-1]
        self.assertEqual(r.volume_spike_status, 'MISSING DATA')
        self.assertTrue(pd.isna(r.volume_daily_accel))

    def test_partial_and_future_days_excluded(self):
        h = history();h.loc[h.index[-1],'volume_24h'] = 1e9
        result = daily_comparisons(h, NOW)
        self.assertEqual(result.time.max(), pd.Timestamp('2026-10-20T00:00Z'))

    def test_zero_baseline_is_explicit_not_infinity(self):
        h = history();h['interactions'] = 0
        h.loc[h.time == pd.Timestamp('2026-10-20T00:00Z'), 'interactions'] = 1000
        r = daily_comparisons(h, NOW).iloc[-1]
        self.assertEqual(r.engagement_spike_status, 'ZERO BASELINE')
        self.assertTrue(pd.isna(r.engagement_spike_multiple))
        self.assertEqual(classify_spike(r), 'INSUFFICIENT DATA')

    def test_daily_jump_increases_score_with_same_trend_features(self):
        base = feature_row(history(), NOW)
        flat = {**base, 'volume_daily_accel':0, 'engagement_daily_accel':0}
        spike = {**base, 'volume_daily_accel':3, 'engagement_daily_accel':2}
        out = score_candidates(pd.DataFrame([flat,spike]), {})
        self.assertGreater(out.loc[1,'breakout_score'],out.loc[0,'breakout_score'])
        self.assertGreater(out.loc[1,'volume_daily_accel_score'],out.loc[0,'volume_daily_accel_score'])
        old = score_candidates(pd.DataFrame([flat,spike]), {'daily_spikes':{'score_share':0}})
        self.assertEqual(old.loc[1,'breakout_score'],old.loc[0,'breakout_score'])

    def test_flags_do_not_require_both_signals(self):
        self.assertEqual(classify_spike({'volume_spike_multiple':3,'engagement_spike_multiple':1}), 'VOLUME')
        self.assertEqual(classify_spike({'volume_spike_multiple':1,'engagement_spike_multiple':2}), 'ENGAGEMENT')
        self.assertEqual(classify_spike({'volume_spike_multiple':1,'engagement_spike_multiple':1}), 'NONE')

    def test_invalid_values_never_become_a_spike(self):
        for v in [-1,np.inf,np.nan]:
            h=history();h.loc[h.time==pd.Timestamp('2026-10-20T00:00Z'),'volume_24h']=v
            r=daily_comparisons(h,NOW).iloc[-1]
            self.assertTrue(pd.isna(r.volume_daily_accel))

    def test_bad_config_rejected(self):
        f=feature_row(history(),NOW)
        for cfg in [{'score_share':2},{'flag_multiple':1}]:
            with self.assertRaises(ValueError):score_candidates(pd.DataFrame([f]),{'daily_spikes':cfg})


if __name__ == '__main__':unittest.main()
