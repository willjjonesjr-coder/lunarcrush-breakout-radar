import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from provisional_ema import report_fields
from sortable_report import payload


class ProvisionalReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'provisional_ema').mkdir()
        self.path = self.root / 'provisional_ema' / 'report.json'
        self.today = datetime.now(timezone.utc).date()
        self.yesterday = (self.today - timedelta(days=1)).isoformat()
        self.asset = dict(coin_id='1', name='Small Coin', symbol='SMALL', status='PROVISIONAL READY',
                          latest_day=self.yesterday, provisional_technical_status='PROVISIONAL EMA ALIGNED',
                          provisional_ema50=1, provisional_ema100=0.9, provisional_ema200=0.8,
                          review_flags=['Missing contract/native-chain documentation'])
        self.report = dict(as_of=self.today.isoformat(), required_completed_day=self.yesterday, assets=[self.asset])

    def save(self):
        self.path.write_text(json.dumps(self.report))

    def test_separate_fields_do_not_change_verified_fields_or_scores(self):
        self.save()
        original = dict(id=1, name='Small Coin', symbol='SMALL', breakout_score=8, market_cap=20,
                        technical_status='EMA NOT CONFIRMED', ema50=500)
        (self.root / 'breakout_radar.json').write_text(json.dumps([original]))
        row = payload(self.root)['groups']['Finalists'][0]
        for key, value in original.items():
            self.assertEqual(row[key], value)
        self.assertEqual(row['provisional_ema50'], 1)
        self.assertIn('Missing contract', row['provisional_review_flags'])

    def test_stale_report_drops_all_ema_values(self):
        self.report['as_of'] = self.yesterday
        self.save()
        row = report_fields(self.path, self.today)['1']
        self.assertEqual(row['provisional_status'], 'STALE PROVISIONAL REPORT')
        self.assertEqual(row['provisional_technical_status'], 'NOT EVALUATED')
        self.assertIsNone(row['provisional_ema50'])

    def test_missing_latest_candle_drops_values(self):
        self.asset['latest_day'] = '2000-01-01'
        self.save()
        self.assertIsNone(report_fields(self.path, self.today)['1']['provisional_ema200'])

    def test_duplicate_ids_not_joined(self):
        self.report['assets'].append(dict(self.asset))
        self.save()
        self.assertEqual(report_fields(self.path, self.today), {})

    def test_identity_changed_since_run_not_joined(self):
        self.save()
        (self.root / 'breakout_radar.json').write_text('[{"id":1,"name":"Other Coin","symbol":"SMALL"}]')
        self.assertNotIn('provisional_ema50', payload(self.root)['groups']['Finalists'][0])

    def test_rejected_history_never_shows_values(self):
        self.asset['status'] = 'HISTORY UNAVAILABLE'
        self.save()
        self.assertIsNone(report_fields(self.path, self.today)['1']['provisional_ema50'])

    def test_malformed_optional_report_does_not_break_verified_view(self):
        for invalid in ('{', 'null', '[1]', '{"assets":[null]}'):
            self.path.write_text(invalid)
            self.assertEqual(report_fields(self.path), {})

    def test_missing_report_keeps_legacy_behavior(self):
        self.assertEqual(report_fields(self.path), {})

if __name__ == '__main__':
    unittest.main()
