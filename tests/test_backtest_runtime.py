"""Exact compatibility tests against the frozen, prefix-by-prefix implementation."""
import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd

import backtest

_spec = importlib.util.spec_from_file_location("backtest_reference", Path(__file__).with_name("backtest_reference.py"))
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)


def history(n=65, seed=1):
    rng = np.random.default_rng(seed)
    result = pd.DataFrame({
        "time": pd.Timestamp("2021-01-01", tz="UTC") + pd.to_timedelta(np.cumsum(rng.integers(1, 4, n)), unit="D"),
        "close": 100 + 22 * np.sin(np.arange(n) / 9 + seed) + np.arange(n) / 4,
        "market_cap": np.full(n, seed * 100000),
    })
    for field in ("posts_active", "contributors_active", "interactions", "sentiment", "social_dominance", "volume_24h", "galaxy_score", "spam"):
        result[field] = rng.uniform(1, 100, n)
    return result


class BacktestRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()

    def save(self, frames):
        for coin, frame in frames.items():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                frame.to_csv(self.data / f"history_{coin}.csv", index=False)

    def assert_rows(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for got, wanted in zip(actual, expected):
            self.assertEqual(list(got), list(wanted), "Field schema/order changed")
        pd.testing.assert_frame_equal(pd.DataFrame(actual), pd.DataFrame(expected), check_exact=True)

    def assert_build(self, thresholds=None, horizons=None, strategies=None, top_n=None):
        thresholds = [20, 35, 55] if thresholds is None else thresholds
        horizons = [7, 14] if horizons is None else horizons
        strategies = ["baseline", "moderate", "strict"] if strategies is None else strategies
        args = (self.data, thresholds, horizons, strategies)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            wanted = legacy.build_backtest_records(*args, top_n=top_n)
            actual = backtest.build_backtest_records(*args, top_n=top_n)
            streamed = self.root / "nested" / "streamed.csv"
            if streamed.exists():
                streamed.write_text("stale output")
            streaming = backtest.build_backtest_records(*args, top_n=top_n, per_signal_path=streamed)
        for got, expected in zip(actual, wanted):
            self.assert_rows(got, expected)
        self.assertEqual(streaming[1], [])
        self.assert_rows(streaming[0], wanted[0])
        self.assert_rows(streaming[2], wanted[2])
        expected_csv = self.root / "expected.csv"
        legacy.write_per_signal_csv(expected_csv, wanted[1])
        self.assertEqual(streamed.read_bytes(), expected_csv.read_bytes())
        # Summary CSVs, as well as row values, preserve formatting and order.
        for index, writer in ((0, legacy.write_csv), (2, legacy.write_tech_summary)):
            writer(self.root / "old.csv", wanted[index])
            writer(self.root / "new.csv", actual[index])
            self.assertEqual((self.root / "old.csv").read_bytes(), (self.root / "new.csv").read_bytes())
        return actual

    def test_full_default_matrix_exact_and_streamed_bytes(self):
        self.save({"alpha": history(), "beta": history(seed=2), "gamma": history(seed=3)})
        rows, hits, technical = self.assert_build(backtest.DEFAULT_THRESHOLDS, backtest.DEFAULT_HORIZONS)
        self.assertEqual(len(rows), 45)
        self.assertTrue(hits)
        self.assertEqual(len(technical), 6)
        self.assertNotIn("threshold", hits[0])  # Legacy duplicates intentionally omit it.
        with (self.root / "expected.csv").open(newline="") as handle:
            self.assertEqual(next(csv.reader(handle)), ["coin_id", "time"] + sorted(k for k in hits[0] if k not in ("coin_id", "time")))

    def test_long_history_technical_summary_exact(self):
        self.save({"alpha": history(210), "beta": history(210, seed=2)})
        _, hits, technical = self.assert_build([0, 35], [0, 7])
        self.assertTrue(any(hit["has_ema200"] for hit in hits))
        self.assertEqual(technical[0]["signals"], len(hits))

    def test_duplicate_parameters_preserve_multiplicity_and_order(self):
        self.save({"alpha": history(35), "beta": history(35, seed=2)})
        records, hits, technical = self.assert_build([0, 0], [0, 0], ["strict", "baseline", "strict"])
        self.assertEqual(len(records), 12)
        self.assertEqual(technical[0]["signals"], len(hits))
        self.assertEqual(sum(row["signals"] for row in records), len(hits))

    def test_empty_and_short_history(self):
        self.assert_build()
        self.save({"short": history(9)})
        self.assert_build()

    def test_no_hits_or_no_future_endpoints(self):
        self.save({"alpha": history(20)})
        rows, hits, technical = self.assert_build([101])
        self.assertTrue(rows)
        self.assertEqual(hits, [])
        self.assertEqual(technical, [])
        self.assert_build([0], [10000])

    def test_missing_close_mixed_and_all(self):
        self.save({"missing": history(35).drop(columns="close"), "present": history(35, 2)})
        self.assert_build()
        (self.data / "history_present.csv").unlink()
        self.assert_build()

    def test_malformed_numeric_nan_zero_and_sparse_columns(self):
        h = history(55)
        for field in h.columns.drop("time"):
            h[field] = h[field].astype(object)
            h.loc[[0, 9, 14, 30], field] = np.nan
            h.loc[[7, 13, 25], field] = 0
            h.loc[19, field] = "invalid"
        self.save({"malformed": h, "sparse": history(55, 2)[["time", "close"]]})
        self.assert_build([0, 40], [-3, 0, 7])

    def test_top_n_loads_same_coins(self):
        self.save({"alpha": history(35), "beta": history(35, 2), "gamma": history(35, 3)})
        rows, hits, _ = self.assert_build([0], [0, 7], top_n=2)
        self.assertEqual({hit["coin_id"] for hit in hits}, {"beta", "gamma"})
        self.assert_build(top_n=0)

    def test_signal_rows_exact_schema_ties_and_missing_close(self):
        for histories in ({}, {"short": history(9)}, {"alpha": history(55), "tie": history(55)},
                          {"missing": history(55).drop(columns="close"), "present": history(55)},
                          {"missing": history(55).drop(columns="close")}):
            with self.subTest(coins=list(histories)):
                expected = legacy.generate_daily_signal_rows(histories)
                actual = backtest.generate_daily_signal_rows(histories)
                pd.testing.assert_frame_equal(actual, expected, check_exact=True)

    def test_indexed_returns_actual_and_between_dates(self):
        h = history(25)
        h.loc[[2, 7, 12], "close"] = np.nan
        h.loc[[5, 15], "close"] = 0
        queries = pd.DatetimeIndex(list(h.time) + list(h.time + pd.Timedelta(hours=12)) +
                                   [h.time.iloc[0] - pd.Timedelta(days=10), h.time.iloc[-1] + pd.Timedelta(days=10), pd.NaT])
        for frame in (h, h.iloc[:0], h.drop(columns="close")):
            for days in (-30, -7, -1, 0, 1, 7, 30):
                for forward in (False, True):
                    with self.subTest(days=days, forward=forward, columns=list(frame), rows=len(frame)):
                        oracle = legacy.forward_return_for if forward else legacy.prior_return_for
                        expected = np.array([oracle(frame, ts, days) for ts in queries])
                        actual = backtest.indexed_returns(frame, queries, days, forward=forward)
                        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(len(backtest.indexed_returns(h, [], 7)), 0)

    def test_missing_endpoint_is_not_skipped(self):
        h = pd.DataFrame({"time": pd.date_range("2021-01-01", periods=5, tz="UTC"), "close": [100., np.nan, 120., 0., 140.]})
        self.assertTrue(np.isnan(backtest.indexed_returns(h, [h.time.iloc[0]], 1, forward=True)[0]))
        self.assertTrue(np.isnan(backtest.indexed_returns(h, [h.time.iloc[2]], 1)[0]))
        self.assertEqual(backtest.indexed_returns(h, [h.time.iloc[2]], 1, forward=True)[0], -1.0)
        self.assertTrue(np.isnan(backtest.indexed_returns(h, [h.time.iloc[4]], 1)[0]))

    def test_progress_covers_each_phase_and_every_combination(self):
        self.save({"alpha": history(20)})
        updates = []
        backtest.build_backtest_records(self.data, [0, 40], [0, 7], ["baseline", "strict"], progress=updates.append)
        text = "\n".join(updates).lower()
        for phase in ("load", "feature", "scor", "return", "summary"):
            self.assertIn(phase, text)
        matrix = [message for message in updates if message.startswith("Matrix ")]
        self.assertEqual(len(matrix), 8)
        for number, message in enumerate(matrix, 1):
            self.assertIn(f"{number}/8", message)

    def test_cli_progress_is_flushed_and_contains_elapsed_time(self):
        argv = ["backtest.py", "--data-dir", str(self.data), "--output", str(self.root / "summary.csv"),
                "--per-signal", str(self.root / "details.csv"), "--tech-summary", str(self.root / "tech.csv")]
        with patch("sys.argv", argv), patch("builtins.print") as output:
            backtest.main()
        progress_calls = [call for call in output.call_args_list if str(call.args[0]).startswith("[backtest ")]
        self.assertTrue(progress_calls)
        for call in progress_calls:
            self.assertRegex(call.args[0], r"^\[backtest \d+\.\d+s\]")
            self.assertIs(call.kwargs.get("flush"), True)
        self.assertTrue((self.root / "details.csv").exists())


if __name__ == "__main__":
    unittest.main()
