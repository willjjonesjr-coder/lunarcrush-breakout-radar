import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.check_backtest_publication import check_staged

ROOT = Path(__file__).resolve().parents[1]


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_cwd = Path.cwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old_cwd)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Publication test')
        self.git('config', 'user.email', 'test@example.com')
        self.git('commit', '--allow-empty', '-qm', 'baseline')

    def git(self, *args):
        return subprocess.check_output(['git', *args], stderr=subprocess.STDOUT)

    def stage(self, path, data=b'summary\n'):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.git('add', '--', path)

    def test_empty_index_is_noop(self):
        self.assertEqual(check_staged(), [])

    def test_both_summaries_allowed(self):
        for path in ('reports/backtest.csv', 'reports/backtest_tech_summary.csv'):
            self.stage(path)
        self.assertEqual(check_staged(), [])

    def test_size_boundary(self):
        self.stage('reports/backtest.csv', b'x' * 10)
        self.assertEqual(check_staged(max_bytes=10), [])
        self.assertIn('exceeding', check_staged(max_bytes=9)[0])

    def test_actual_default_limit(self):
        self.stage('reports/backtest.csv', b'x' * (10 * 1024 * 1024 + 1))
        self.assertIn('exceeding', check_staged()[0])

    def test_checks_index_not_worktree(self):
        self.stage('reports/backtest.csv', b'x' * 11)
        Path('reports/backtest.csv').write_bytes(b'x')
        self.assertIn('exceeding', check_staged(max_bytes=10)[0])

    def test_detail_and_unexpected_paths_rejected(self):
        for path in ('reports/backtest_per_coin.csv', 'reports/backtest_events.csv', 'unexpected\nfile.csv'):
            self.stage(path)
        self.assertEqual(len(check_staged()), 3)
        self.assertTrue(all('Unexpected staged path' in error for error in check_staged()))

    def test_summary_deletion_rejected(self):
        self.stage('reports/backtest.csv')
        self.git('commit', '-qm', 'summary')
        self.git('rm', 'reports/backtest.csv')
        self.assertIn('deletion', check_staged()[0])

    def test_summary_symlink_rejected(self):
        Path('reports').mkdir()
        Path('reports/backtest.csv').symlink_to('../outside.csv')
        self.git('add', 'reports/backtest.csv')
        self.assertIn('symlink', check_staged()[0])

    def test_rename_outside_allowlist_rejected(self):
        self.stage('reports/backtest.csv')
        self.git('commit', '-qm', 'summary')
        self.git('mv', 'reports/backtest.csv', 'reports/other.csv')
        self.assertEqual(len(check_staged()), 2)

    def test_cli_rejects_oversized_index(self):
        self.stage('reports/backtest.csv', b'x' * (10 * 1024 * 1024 + 1))
        result = subprocess.run([sys.executable, str(ROOT / 'tools/check_backtest_publication.py')], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'exceeding', result.stderr)

    def test_executable_mode_rejected(self):
        self.stage('reports/backtest.csv')
        self.git('update-index', '--chmod=+x', 'reports/backtest.csv')
        self.assertIn('regular staged summary', check_staged()[0])

    def test_command_fails_closed_outside_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(ROOT / 'tools/check_backtest_publication.py')], cwd=folder, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_current_outputs_preserved_and_only_summaries_committed(self):
        # The old detail remains tracked but unchanged. New detail stays on disk
        # for upload, including when it is much larger than publication's limit.
        self.stage('reports/backtest_per_coin.csv', b'historical snapshot\n')
        Path('.gitignore').write_text((ROOT / '.gitignore').read_text())
        self.git('add', '.gitignore')
        self.git('commit', '-qm', 'historical report and artifact ignore')
        Path('data').mkdir()
        subprocess.run([
            sys.executable, str(ROOT / 'backtest.py'), '--data-dir', 'data',
            '--output', 'reports/backtest.csv',
            '--per-signal', 'reports/backtest_artifacts/backtest_per_coin.csv',
            '--tech-summary', 'reports/backtest_tech_summary.csv',
        ], check=True, capture_output=True)
        detail = Path('reports/backtest_artifacts/backtest_per_coin.csv')
        self.assertTrue(detail.exists())
        with detail.open('wb') as handle:
            handle.truncate(610 * 1024 * 1024)
        self.git('add', '--', 'reports/backtest.csv', 'reports/backtest_tech_summary.csv')
        self.assertEqual(check_staged(), [])
        self.git('commit', '-qm', 'publish summaries')
        self.assertEqual(self.git('status', '--porcelain'), b'')
        self.assertEqual(detail.stat().st_size, 610 * 1024 * 1024)
        self.assertEqual(Path('reports/backtest_per_coin.csv').read_bytes(), b'historical snapshot\n')
        self.assertIn(b'strategy,threshold', Path('reports/backtest.csv').read_bytes())
        self.assertIn(b'condition,signals', Path('reports/backtest_tech_summary.csv').read_bytes())

    def test_workflow_publishes_fresh_outputs_before_guard(self):
        workflow = (ROOT / '.github/workflows/backtest.yml').read_text()
        self.assertIn('--per-signal reports/backtest_artifacts/backtest_per_coin.csv', workflow)
        self.assertIn('git add -- reports/backtest.csv reports/backtest_tech_summary.csv', workflow)
        self.assertNotIn('reports/backtest*.csv', workflow)
        self.assertLess(workflow.index('actions/upload-artifact@v4'), workflow.index('python tools/check_backtest_publication.py'))
        self.assertLess(workflow.index('python tools/check_backtest_publication.py'), workflow.index('git commit'))


if __name__ == '__main__':
    unittest.main()
