"""Offline safety regression tests for provisional research histories."""
import copy
import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import provisional_ema as p

TODAY = date(2026, 11, 4)
LAST = TODAY - timedelta(days=1)
LC = {'id': '123', 'name': 'Tiny Coin', 'symbol': 'TINY', 'market_cap': 25}
CG = {'id': 'tiny-coin', 'name': 'Tiny Coin', 'symbol': 'tiny', 'platforms': {}}


def candles(n=300, last=LAST):
    return [[int(datetime.combine(last - timedelta(days=n-i-1), datetime.min.time(), timezone.utc).timestamp()*1000),
             100+i, 102+i, 99+i, 101+i, 25] for i in range(n)]


def listing(**kw):
    return dict({'market': {'identifier': 'kraken'}, 'base': 'TINY', 'target': 'USD',
                 'coin_id': 'tiny-coin', 'is_stale': False, 'is_anomaly': False}, **kw)


class FakeExchange:
    def __init__(self, rows=None, pages=None):
        self.markets = {'TINY/USD': {'spot': True, 'active': True, 'base': 'TINY', 'quote': 'USD'}}
        self.has = {'fetchOHLCV': True}
        self.rows = candles() if rows is None else rows
        self.pages = list(pages) if pages is not None else None
        self.calls = []
        self.loaded = False

    def load_markets(self):
        self.loaded = True

    def fetch_ohlcv(self, pair, timeframe, since, limit):
        self.calls.append((pair, timeframe, since, limit))
        if self.pages is not None:
            return self.pages.pop(0) if self.pages else []
        return [r for r in self.rows if r[0] >= since][:limit]


class IdentityTests(unittest.TestCase):
    def match(self, lc=None, cg=None, registry=None):
        return p.match_identities(lc or [LC], cg or [CG], registry)['123']

    def test_conservative_normalization_and_low_cap(self):
        row = dict(LC, name='  TINY   coin ', symbol=' tiny ')
        result = self.match([row])
        self.assertEqual(result['status'], 'MATCHED PROVISIONALLY')
        self.assertFalse(result['eligible_for_alerts'])
        self.assertFalse(result['eligible_for_verified_inventory'])
        self.assertTrue(any('Missing' in f for f in result['review_flags']))

    def test_no_ticker_only_alias_or_punctuation_join(self):
        for name in ('Other Coin', 'Tiny-Coin', 'TinyCoin'):
            with self.subTest(name=name):
                self.assertEqual(self.match(cg=[dict(CG, name=name)])['status'], 'REVIEW REQUIRED')

    def test_collisions_in_both_full_snapshots(self):
        cases = [([LC, dict(LC, id='456')], [CG]),
                 ([LC, dict(LC, name='Other')], [CG]),
                 ([LC], [CG, dict(CG, id='tiny-duplicate')]),
                 ([LC], [CG, dict(CG, name='Other')])]
        for lc, cg in cases:
            with self.subTest(lc=lc, cg=cg):
                self.assertEqual(self.match(lc, cg)['status'], 'REVIEW REQUIRED')

    def test_explicit_canonical_id_conflicts(self):
        self.assertEqual(self.match([dict(LC, coingecko_id='other')])['status'], 'REVIEW REQUIRED')
        for field in ('canonical_id', 'coingecko_id'):
            self.assertEqual(self.match(registry={'123': {field: 'other'}})['status'], 'REVIEW REQUIRED')

    def test_contract_conflicts_and_missing_documentation(self):
        lc = dict(LC, platforms={'ethereum': '0x'+'a'*40})
        cg = dict(CG, platforms={'ethereum': '0x'+'b'*40})
        self.assertEqual(self.match([lc], [cg])['status'], 'REVIEW REQUIRED')
        cg['platforms']['ethereum'] = '0x'+'A'*40
        self.assertEqual(self.match([lc], [cg])['status'], 'MATCHED PROVISIONALLY')
        self.assertTrue(p.contract_conflict({'solana': 'AbC'}, {'solana': 'abc'}))
        self.assertEqual(self.match([lc], [CG])['status'], 'MATCHED PROVISIONALLY')

    def test_malformed_contract_evidence_withheld(self):
        for bad in ('not json', '[1]', [1], 12):
            with self.subTest(bad=bad):
                self.assertEqual(self.match([dict(LC, platforms=bad)])['status'], 'REVIEW REQUIRED')
                self.assertEqual(self.match(cg=[dict(CG, platforms=bad)])['status'], 'REVIEW REQUIRED')

    def test_json_encoded_platforms_are_supported(self):
        lc = dict(LC, platforms=json.dumps({'ethereum': 'a'}))
        cg = dict(CG, platforms={'ethereum': 'b'})
        self.assertEqual(self.match([lc], [cg])['status'], 'REVIEW REQUIRED')

    def test_invalid_identity(self):
        for key in ('name', 'symbol'):
            self.assertEqual(self.match([dict(LC, **{key: ''})])['status'], 'REVIEW REQUIRED')
        self.assertEqual(p.match_identities([dict(LC, id='../123')], [CG])['../123']['status'], 'REVIEW REQUIRED')


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.identity = p.match_identities([LC], [CG])['123']

    def test_exact_market_identifiers_and_pairs(self):
        self.assertEqual(p.corroborated_pairs(self.identity, CG, [listing()]), [('kraken', 'TINY/USD')])
        self.assertEqual(p.corroborated_pairs(self.identity, CG, [listing(market={'identifier': 'gdax'}, target='USDT')]), [('coinbase', 'TINY/USDT')])
        for ticker in [listing(market={'identifier': 'Kraken'}), listing(market={'name': 'Kraken'}),
                       listing(base='XTINY'), listing(target='USDC'), listing(market={'identifier': 'coinbase'})]:
            self.assertEqual(p.corroborated_pairs(self.identity, CG, [ticker]), [])

    def test_stale_anomalous_and_conflicting_listing(self):
        for kw in ({'is_stale': True}, {'is_anomaly': True}):
            self.assertEqual(p.corroborated_pairs(self.identity, CG, [listing(**kw)]), [])
        with self.assertRaises(ValueError):
            p.corroborated_pairs(self.identity, CG, [listing(coin_id='another')])

    def test_detail_changes_withhold(self):
        for changed in (dict(CG, id='other'), dict(CG, name='Other'), dict(CG, symbol='OTHR')):
            with self.assertRaises(ValueError):
                p.corroborated_pairs(self.identity, changed, [listing()])
        self.identity['platforms'] = {'ethereum': 'one'}
        with self.assertRaises(ValueError):
            p.corroborated_pairs(self.identity, dict(CG, platforms={'ethereum': 'two'}), [listing()])


class CandleTests(unittest.TestCase):
    def test_complete_current_and_unfinished_day_excluded(self):
        rows = candles(310)
        result = p.validate_candles(rows + candles(1, TODAY), LAST)
        self.assertEqual(len(result), 300)
        self.assertEqual(result[-1][0], LAST.isoformat()+'T00:00:00Z')
        with self.assertRaises(ValueError):
            p.validate_candles(rows, LAST, 299)

    def test_short_gapped_stale_and_conflicting_duplicate_rejected(self):
        rows = candles()
        changed = rows[-1][:]
        changed[5] += 1
        cases = [rows[:-1], candles(299), candles(300, LAST-timedelta(days=1)),
                 candles(301)[:100] + candles(301)[101:], rows+[changed]]
        for bad in cases:
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                p.validate_candles(bad, LAST)

    def test_invalid_nonfinite_misaligned_future_candles(self):
        for index, value in ((0, float('nan')), (0, 1), (1, 0), (2, 1), (3, 100000),
                             (4, float('inf')), (5, -1), (5, float('nan'))):
            rows = candles()
            rows[100][index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                p.validate_candles(rows, LAST)
        with self.assertRaises(ValueError):
            p.validate_candles(candles()+candles(1, TODAY+timedelta(days=1)), LAST)
        with self.assertRaises(ValueError):
            p.validate_candles([[1, 2]], LAST)

    def test_paginated_fetch_keeps_full_300_bars(self):
        rows = candles()
        client = FakeExchange(pages=[rows[:100], rows[100:200], rows[200:]])
        result = p.fetch_history(client, 'TINY/USD', LAST, 300)
        self.assertEqual(len(result), 300)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(client.calls[1][2], rows[99][0]+86400000)
        self.assertTrue(all(c[1] == '1d' for c in client.calls))

    def test_identical_pagination_overlap_is_deduplicated(self):
        rows = candles()
        client = FakeExchange(pages=[rows[:160], rows[150:]])
        self.assertEqual(len(p.fetch_history(client, 'TINY/USD', LAST, 300)), 300)
        changed = copy.deepcopy(rows[150:])
        changed[0][5] += 1
        client = FakeExchange(pages=[rows[:160], changed])
        with self.assertRaises(ValueError):
            p.fetch_history(client, 'TINY/USD', LAST, 300)

    def test_pagination_no_progress_does_not_loop_forever(self):
        rows = candles(100, LAST-timedelta(days=5))
        client = FakeExchange(pages=[rows, rows])
        with self.assertRaises(ValueError):
            p.fetch_history(client, 'TINY/USD', LAST, 300)
        self.assertEqual(len(client.calls), 2)

    def test_exact_active_spot_market_before_fetch(self):
        for key, value in (('spot', False), ('active', False), ('base', 'OTHER'), ('quote', 'USDT')):
            client = FakeExchange()
            client.markets['TINY/USD'][key] = value
            with self.assertRaises(ValueError):
                p.fetch_history(client, 'TINY/USD', LAST, 300)
            self.assertEqual(client.calls, [])

    def test_ema_band_inclusive_and_strict_stack(self):
        def fake_ema(prices, period):
            return [99]*294+[100 if period == 50 else (90 if period == 100 else 80)]*6 if period != 50 else [99]*295+[100]*5
        for price, aligned in ((97, True), (110, True), (96.999, False), (110.001, False)):
            rows = [[None, 0, 0, 0, price, 0] for _ in range(300)]
            with patch.object(p, 'ema', side_effect=fake_ema):
                status = p.provisional_technicals(rows)['provisional_technical_status']
            self.assertEqual(status, 'PROVISIONAL EMA '+('ALIGNED' if aligned else 'NOT ALIGNED'))
        with patch.object(p, 'ema', return_value=[100]*300):
            self.assertEqual(p.provisional_technicals(rows)['provisional_technical_status'], 'PROVISIONAL EMA NOT ALIGNED')


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)/'provisional_ema'
        self.client = FakeExchange()
        self.fetches = []

    def build(self, **kw):
        def detail(cid):
            self.fetches.append(('detail', cid))
            return copy.deepcopy(CG)
        def tickers(cid):
            self.fetches.append(('tickers', cid))
            return [listing()]
        def factory(name):
            self.fetches.append(('exchange', name))
            return self.client
        args = dict(universe=[LC], targets=[LC], catalog=[CG], detail_fetch=detail,
                    ticker_fetch=tickers, exchange_factory=factory, output_dir=self.output, today=TODAY)
        args.update(kw)
        return p.build(**args)['assets'][0]

    def test_low_cap_included_and_output_strictly_separate(self):
        sentinel = Path(self.tmp.name)/'123.csv'
        sentinel.write_text('verified unchanged')
        item = self.build()
        self.assertEqual(item['status'], 'PROVISIONAL READY')
        self.assertFalse(item['eligible_for_alerts'])
        self.assertFalse(item['eligible_for_verified_inventory'])
        self.assertEqual([f[0] for f in self.fetches], ['detail', 'tickers', 'exchange'])
        self.assertEqual(sentinel.read_text(), 'verified unchanged')
        with (self.output/'123.csv').open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 300)
        self.assertEqual(rows[-1]['pair'], 'TINY/USD')
        self.assertEqual(json.loads((self.output/'report.json').read_text())['assets'][0], item)
        with self.assertRaises(ValueError):
            self.build(output_dir=Path(self.tmp.name)/'verified')

    def test_no_history_fetch_without_listing(self):
        item = self.build(ticker_fetch=lambda cid: [])
        self.assertEqual(item['status'], 'REVIEW REQUIRED')
        self.assertFalse(self.client.loaded)
        self.assertEqual(self.client.calls, [])

    def test_failure_removes_previous_output(self):
        self.build()
        self.assertTrue((self.output/'123.csv').exists())
        self.client.rows = candles(299)
        self.assertEqual(self.build()['status'], 'HISTORY UNAVAILABLE')
        self.assertFalse((self.output/'123.csv').exists())
        self.client.rows = candles()
        self.build()
        self.build(targets=[dict(LC, name='Other')])
        self.assertFalse((self.output/'123.csv').exists())

    def test_ambiguous_unselected_universe_row_blocks_target(self):
        item = self.build(universe=[LC, dict(LC, id='999')])
        self.assertEqual(item['status'], 'REVIEW REQUIRED')
        self.assertEqual(self.fetches, [])

    def test_target_identity_and_duplicate_target_conflicts(self):
        for targets in ([dict(LC, name='Other')], [LC, LC], [dict(LC, id='456')]):
            self.fetches.clear()
            self.assertEqual(self.build(targets=targets)['status'], 'REVIEW REQUIRED')
            self.assertEqual(self.fetches, [])

    def test_malformed_target_evidence_withheld_without_fetch(self):
        item = self.build(targets=[dict(LC, platforms='invalid json')])
        self.assertEqual(item['status'], 'REVIEW REQUIRED')
        self.assertEqual(self.fetches, [])

    def test_interruption_invalidates_old_report(self):
        self.build()
        def interrupted(_):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.build(detail_fetch=interrupted)
        report = json.loads((self.output/'report.json').read_text())
        self.assertEqual(report['assets'], [])
        self.assertFalse((self.output/'report.json.tmp').exists())

    def test_early_matching_failure_invalidates_old_report(self):
        self.build()
        with patch.object(p, 'match_identities', side_effect=ValueError('malformed snapshot')):
            with self.assertRaises(ValueError):
                self.build()
        report = json.loads((self.output/'report.json').read_text())
        self.assertEqual(report['assets'], [])

    def test_interruption_preserves_completed_checkpoint(self):
        other = dict(LC, id='456', name='Other Coin', symbol='OTHER')
        other_cg = dict(CG, id='other-coin', name='Other Coin', symbol='OTHER')
        def detail(cid):
            if cid == 'other-coin':
                raise KeyboardInterrupt()
            return CG
        with self.assertRaises(KeyboardInterrupt):
            self.build(universe=[LC, other], targets=[LC, other], catalog=[CG, other_cg], detail_fetch=detail)
        report = json.loads((self.output/'report.json').read_text())
        self.assertEqual(len(report['assets']), 1)
        self.assertEqual(report['assets'][0]['status'], 'PROVISIONAL READY')
        self.assertEqual(report['counts'], {'PROVISIONAL READY': 1})

    def test_target_explicit_canonical_conflict_withheld(self):
        self.assertEqual(self.build(targets=[dict(LC, coingecko_id='other')])['status'], 'REVIEW REQUIRED')
        self.assertEqual(self.fetches, [])

    def test_target_explicit_contract_conflict_withheld(self):
        lc = dict(LC, platforms={'ethereum': 'a'})
        cg = dict(CG, platforms={'ethereum': 'a'})
        item = self.build(universe=[lc], targets=[dict(lc, platforms={'ethereum': 'b'})], catalog=[cg], detail_fetch=lambda _: cg)
        self.assertEqual(item['status'], 'REVIEW REQUIRED')
        self.assertEqual(self.fetches, [])


if __name__ == '__main__':
    unittest.main()
