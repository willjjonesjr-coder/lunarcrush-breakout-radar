import json
import tempfile
import unittest
from pathlib import Path
from sortable_report import build, payload


class SortableReportTests(unittest.TestCase):
    def test_merges_fundamentals_by_id_without_replacing_candidate_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'breakout_radar.json').write_text(json.dumps([{'id':1,'breakout_score':9,'fundamentals_fdv_to_market_cap':2}]))
            (p/'radar_candidates.json').write_text(json.dumps([{'id':1,'breakout_score':8},{'id':2,'breakout_score':7}]))
            rows=payload(p)['groups']['All candidates']
            self.assertEqual(rows[0]['breakout_score'],8)
            self.assertEqual(rows[0]['fundamentals_fdv_to_market_cap'],2)
            self.assertNotIn('fundamentals_fdv_to_market_cap',rows[1])

    def test_old_reports_work_with_new_metrics_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'breakout_radar.json').write_text('[{"id":1,"stage":"WEAK","breakout_score":null}]')
            data=payload(p)
            self.assertEqual(list(data['groups']),['Finalists'])
            self.assertEqual(data['groups']['Finalists'][0]['stage'],'INSUFFICIENT DATA')
            self.assertIn('volume_daily_accel',[m['key'] for m in data['metrics']])

    def test_embedded_data_cannot_close_script_or_inject_markup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'breakout_radar.json').write_text(json.dumps([{'name':'</script><script>alert(1)</script>'}]))
            build(p,p/'result.html');html=(p/'result.html').read_text()
            self.assertNotIn('</script><script>alert',html)
            self.assertIn('\\u003c/script',html)
            self.assertNotIn('/*__REPORT_DATA__*/',html)
            self.assertNotIn('/*__SORT_LOGIC__*/',html)

    def test_empty_reports_generate_valid_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'breakout_radar.json').write_text('[]')
            build(p,p/'result.html')
            self.assertIn('const report=',(p/'result.html').read_text())


if __name__=='__main__':unittest.main()
