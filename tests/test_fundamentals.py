import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import fundamentals as f

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
END = int(NOW.timestamp()) // 86400 * 86400


def chart(n=365):
    return {'totalDataChart': [[END - 86400*i, 20 if i <= 30 else 10] for i in range(1, n+1)]}


class FakeSource:
    now = NOW

    def get(self, url, params=None, headers=None):
        if url.endswith('/coins/list'):
            data = [{'id': 'example', 'symbol': 'ex', 'name': 'Example'}]
        elif url.endswith('/coins/markets'):
            data = [{'id': 'example', 'market_cap': 1000, 'fully_diluted_valuation': 2000,
                     'last_updated': NOW.isoformat()}]
        elif url.endswith('/protocols'):
            data = [{'gecko_id': 'example', 'slug': 'example', 'category': 'Lending', 'tvl': 50}]
        else:
            data = {**chart(), 'gecko_id': 'example'}
        return {'data': data, 'url': url, 'fetched_at': NOW.timestamp()}


class FundamentalsTests(unittest.TestCase):
    def test_complete_windows_and_incomplete_today(self):
        payload = chart()
        payload['totalDataChart'].append([END, 999999])
        out = f.window_metrics(payload, NOW)
        self.assertEqual(out['30d'], 600)
        self.assertEqual(out['previous_30d'], 300)
        self.assertEqual(out['growth_30d'], 1)
        self.assertEqual(out['365d'], 3950)

    def test_missing_day_is_unknown_not_zero(self):
        payload = chart()
        payload['totalDataChart'].pop(0)
        out = f.window_metrics(payload, NOW)
        self.assertIsNone(out['30d'])
        self.assertIsNone(out['growth_30d'])
        self.assertIsNone(out['365d'])

    def test_zero_baseline_no_infinite_growth(self):
        payload = {'totalDataChart': [[END-86400*i, 0] for i in range(1,61)]}
        self.assertIsNone(f.window_metrics(payload, NOW)['growth_30d'])
        self.assertIsNone(f.ratio(100, 0))
        self.assertIsNone(f.number(float('inf')))

    def test_ambiguous_identity_is_rejected(self):
        coins = [{'id': 'one', 'symbol': 'EX', 'name': 'Example'},
                 {'id': 'two', 'symbol': 'EX', 'name': 'Example'}]
        out = f.assess({'symbol': 'EX', 'name': 'Example'}, coins, {}, [], FakeSource())
        self.assertEqual(out['fundamentals_status'], 'INSUFFICIENT DATA')
        self.assertNotIn('fundamentals_coingecko_id', out)

    def test_enrichment_preserves_scores_and_order(self):
        radar = pd.DataFrame([{'symbol': 'EX', 'name': 'Example', 'breakout_score': 42},
                              {'symbol': 'OTHER', 'name': 'Other', 'breakout_score': 80}])
        out = f.enrich(radar, FakeSource())
        pd.testing.assert_frame_equal(out[radar.columns], radar)
        self.assertEqual(out.iloc[0]['fundamentals_status'], 'IMPROVING')
        self.assertEqual(out.iloc[1]['fundamentals_status'], 'INSUFFICIENT DATA')
        self.assertAlmostEqual(out.iloc[0]['fundamentals_market_cap_to_holder_revenue_365d'], 1000/3950)

    def test_ambiguous_protocol_not_combined(self):
        coin = {'id': 'example', 'symbol': 'ex', 'name': 'Example'}
        protocols = [{'gecko_id': 'example', 'slug': 'v1'}, {'gecko_id': 'example', 'slug': 'v2'}]
        out = f.assess(coin, [coin], {}, protocols, FakeSource())
        self.assertNotIn('fundamentals_defillama_slug', out)

    def test_outages_still_produce_unknown_overlay(self):
        class Down(FakeSource):
            def get(self, *a, **kw): return None
        out = f.enrich(pd.DataFrame([{'symbol': 'EX', 'name': 'Example', 'breakout_score': 42}]), Down())
        self.assertEqual(out.iloc[0]['breakout_score'], 42)
        self.assertEqual(out.iloc[0]['fundamentals_confidence'], 'INSUFFICIENT')

    def test_response_identity_mismatch_is_unknown(self):
        class Wrong(FakeSource):
            def get(self, *a, **kw):
                record = super().get(*a, **kw)
                record['data']['gecko_id'] = 'different-token'
                return record
        coin = {'id': 'example', 'symbol': 'ex', 'name': 'Example'}
        out = f.assess(coin, [coin], {}, [{'gecko_id': 'example', 'slug': 'example'}], Wrong())
        self.assertEqual(out['fundamentals_status'], 'INSUFFICIENT DATA')
        self.assertIsNone(out['fundamentals_revenue_30d'])

    def test_parent_summary_used_without_child_tvl(self):
        coin = {'id': 'example', 'symbol': 'ex', 'name': 'Example'}
        protocols = [{'gecko_id': 'example', 'slug': 'example-v1',
                      'parentProtocol': 'parent#example', 'tvl': 100}]
        out = f.assess(coin, [coin], {}, protocols, FakeSource())
        self.assertEqual(out['fundamentals_defillama_slug'], 'example')
        self.assertIsNone(out['fundamentals_tvl_usd'])

    def test_budget_prevents_network(self):
        with tempfile.TemporaryDirectory() as cache, patch('fundamentals.requests.get') as get:
            source = f.Source(cache, now=NOW, budget=0)
            self.assertIsNone(source.get('https://example.test'))
            get.assert_not_called()

    def test_cache_reuses_original_fetch_time(self):
        with tempfile.TemporaryDirectory() as cache, patch('fundamentals.requests.get') as get:
            source = f.Source(cache, now=NOW)
            url = 'https://example.test'
            key = f.hashlib.sha256(json.dumps([url, None], sort_keys=True).encode()).hexdigest()
            original = NOW.timestamp()-3600
            Path(cache, key+'.json').write_text(json.dumps({'fetched_at': original, 'data': []}))
            self.assertEqual(source.get(url)['fetched_at'], original)
            get.assert_not_called()

    def test_stale_market_not_used_for_valuation(self):
        coin = {'id': 'example', 'symbol': 'ex', 'name': 'Example'}
        markets = {'example': {'market_cap': 100, 'last_updated': '2020-01-01T00:00:00Z'}}
        out = f.assess(coin, [coin], markets, [], FakeSource())
        self.assertIsNone(out['fundamentals_market_cap'])


if __name__ == '__main__': unittest.main()
