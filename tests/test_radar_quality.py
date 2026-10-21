import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import scanner
from radar_quality import (REQUIRED_FEATURES, annotate_assets, classify_asset,
                           coverage, daily_history, merge_history)

NOW = pd.Timestamp('2026-10-21T12:00:00Z')


def history():
    dates = pd.date_range('2026-08-01', '2026-10-21', tz='UTC')
    h = pd.DataFrame({'time': dates})
    for col in ['close', 'posts_active', 'contributors_active', 'interactions',
                'sentiment', 'social_dominance', 'volume_24h', 'galaxy_score', 'spam']:
        h[col] = np.linspace(10, 20, len(h))
    return h


class RadarQualityTests(unittest.TestCase):
    def test_partial_current_day_cannot_erase_score(self):
        h = history()
        h.loc[h.index[-1], ['close', 'galaxy_score', 'social_dominance']] = np.nan
        features = scanner.feature_row(h, NOW)
        scored = scanner.score_candidates(pd.DataFrame([features]), {})
        self.assertEqual(features['last_time'], pd.Timestamp('2026-10-20T00:00Z'))
        self.assertEqual(scored.iloc[0].data_status, 'COMPLETE')
        self.assertTrue(np.isfinite(scored.iloc[0].breakout_score))

    def test_sparse_refresh_preserves_known_values_but_accepts_revisions(self):
        old = history().tail(1)
        fresh = old.copy()
        fresh['close'] = np.nan
        fresh['posts_active'] = 99
        out = merge_history(old, fresh)
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]['close'], old.iloc[0]['close'])
        self.assertEqual(out.iloc[0]['posts_active'], 99)

    def test_calendar_gap_is_not_a_shorter_return_window(self):
        h = history()
        h = h[h.time != pd.Timestamp('2026-10-13T00:00Z')]
        features = scanner.feature_row(h, NOW)
        self.assertFalse(features['history_complete_30d'])
        score = scanner.score_candidates(pd.DataFrame([features]), {}).iloc[0]
        self.assertEqual(score.stage, 'INSUFFICIENT DATA')
        self.assertTrue(pd.isna(score.breakout_score))

    def test_missing_latest_closed_price_is_not_forward_filled(self):
        h = history()
        h.loc[h.time == pd.Timestamp('2026-10-20T00:00Z'), 'close'] = np.nan
        f = scanner.feature_row(h, NOW)
        self.assertTrue(pd.isna(f['last_price']))
        self.assertEqual(scanner.score_candidates(pd.DataFrame([f]), {}).iloc[0].stage,
                         'INSUFFICIENT DATA')

    def test_missing_feature_never_becomes_neutral_score(self):
        f = scanner.feature_row(history(), NOW)
        f['galaxy_score_change'] = np.nan
        out = scanner.score_candidates(pd.DataFrame([f]), {}).iloc[0]
        self.assertTrue(pd.isna(out.breakout_score))
        self.assertIn('galaxy_score_change', out.missing_features)

    def test_incomplete_candidate_cannot_distort_valid_scores(self):
        a = scanner.feature_row(history(), NOW)
        b = {**a, 'social_accel': a['social_accel']+1}
        invalid = {**a, 'social_accel': 1e9, 'last_price': np.nan}
        expected = scanner.score_candidates(pd.DataFrame([a,b]), {})
        actual = scanner.score_candidates(pd.DataFrame([a,b,invalid]), {})
        pd.testing.assert_series_equal(expected.breakout_score, actual.breakout_score.iloc[:2])

    def test_future_bars_never_used(self):
        a = scanner.feature_row(history(), NOW)
        future = history().tail(1).copy()
        future['time'] = NOW.normalize()+pd.Timedelta(days=1)
        future['close'] = 1e9
        b = scanner.feature_row(pd.concat([history(), future]), NOW)
        self.assertEqual(a['last_price'], b['last_price'])
        self.assertEqual(a['price_change_7d'], b['price_change_7d'])

    def test_zero_spam_stays_zero_without_infinite_growth(self):
        h = history(); h['spam'] = 0
        self.assertEqual(scanner.feature_row(h, NOW)['spam_change'], 0)
        h['social_dominance'] = 0
        self.assertEqual(scanner.feature_row(h, NOW)['social_dominance_change'], 0)

    def test_bad_prices_fail_coverage(self):
        for value in [0, -1, np.inf]:
            h = history()
            h.loc[h.time == pd.Timestamp('2026-10-20T00:00Z'), 'close'] = value
            self.assertFalse(scanner.feature_row(h, NOW)['history_complete_30d'])

    def test_asset_types_separated_without_ticker_only_guess(self):
        for row, expected in [({'symbol':'USDG','name':'Global Dollar'},'stablecoin'),
                              ({'symbol':'CBBTC','name':'CBBTC'},'wrapped_asset'),
                              ({'symbol':'INTCX','name':'Intel xStock'},'tokenized_security'),
                              ({'symbol':'INTCB','name':'Intel (Tokenized Stock)'},'tokenized_security'),
                              ({'symbol':'XAUT','name':'Tether Gold'},'commodity_backed'),
                              ({'symbol':'USDG','name':'Unrelated Project'},'unclassified_crypto')]:
            self.assertEqual(classify_asset(row)[0], expected)
        self.assertEqual(classify_asset({'symbol':'EX','name':'Example','tags':['stablecoin']})[0], 'stablecoin')

    def test_failed_history_and_separated_assets_visible_in_reports(self):
        universe = pd.DataFrame([
            {'id':1,'symbol':'EX','name':'Example'},
            {'id':2,'symbol':'FAIL','name':'Failure'},
            {'id':53664,'symbol':'USDG','name':'Global Dollar'}])
        for c in ['market_cap','volume_24h','social_volume_24h','interactions_24h',
                  'social_dominance','sentiment','galaxy_score']:
            universe[c] = 100
        cfg = {'base_url':'unused','requests_per_minute':10,'daily_request_budget':2000,
               'universe':{'page_size':1000,'min_market_cap':0,'max_market_cap':1000,
                           'min_volume_24h':0,'max_7d_price_change':35,'exclude_symbols':[]},
               'funnel':{'historical_candidates':60,'finalists':15}}
        def fetch(client, coin_id, config):
            if coin_id == 2: raise ValueError('unavailable')
            self.assertEqual(coin_id, 1)
            # Relative fixture so this integration test stays valid in future CI runs.
            h = history(); h.time += pd.Timestamp.now(tz='UTC').normalize()-NOW.normalize()
            return h
        with tempfile.TemporaryDirectory() as tmp:
            cfg['output']={'data_dir':tmp+'/data','reports_dir':tmp+'/reports'}
            with patch('scanner.load_config',return_value=cfg), patch('scanner.LunarCrushClient'), \
                 patch('scanner.fetch_universe',return_value=universe), \
                 patch('scanner.fetch_history',side_effect=fetch), patch('sys.argv',['scanner.py']):
                scanner.main()
            reports = Path(tmp,'reports')
            ranked = pd.read_json(reports/'breakout_radar.json')
            self.assertEqual(ranked.symbol.tolist(), ['EX'])
            candidates = pd.read_json(reports/'radar_candidates.json')
            self.assertEqual(candidates[candidates.symbol=='FAIL'].iloc[0].stage,'INSUFFICIENT DATA')
            separated = pd.read_json(reports/'separated_assets.json')
            self.assertEqual(separated.symbol.tolist(), ['USDG'])
            summary = json.loads((reports/'radar_coverage.json').read_text())
            self.assertEqual(summary['scored_candidates'],1)
            self.assertEqual(summary['history_candidates'],2)
            self.assertEqual(summary['separated_assets'],1)


if __name__ == '__main__': unittest.main()
