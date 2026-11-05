import unittest
import warnings

import numpy as np
import pandas as pd

from backtest_features import EMA_COLUMNS, FEATURE_COLUMNS, historical_features
from signals import ema_features, feature_row


def representative_history(n=240):
    rng = np.random.default_rng(1729)
    h = pd.DataFrame({
        "time": pd.Timestamp("2020-01-01", tz="UTC") + pd.to_timedelta(np.cumsum(rng.integers(1, 4, n)), unit="D"),
        "close": 100 + 30 * np.sin(np.arange(n) / 13) + np.arange(n) / 10,
    })
    for column in ("posts_active", "contributors_active", "interactions", "sentiment", "social_dominance", "volume_24h", "galaxy_score", "spam"):
        h[column] = rng.uniform(1, 100, n)
    return h


class HistoricalFeatureTests(unittest.TestCase):
    def assert_oracle(self, hist):
        actual = historical_features(hist)
        self.assertEqual(list(actual.columns), list(FEATURE_COLUMNS + (EMA_COLUMNS if "close" in hist else ())))
        pd.testing.assert_index_equal(actual.index, hist.index[9:])
        expected = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for end in range(10, len(hist) + 1):
                prefix = hist.iloc[:end]
                row = feature_row(prefix)
                row.update(ema_features(prefix, require_200=False) or {})
                expected.append(row)
        expected = pd.DataFrame(expected, index=hist.index[9:], columns=actual.columns)
        pd.testing.assert_frame_equal(actual, expected, check_exact=True, check_dtype=False)
        return actual

    def test_every_prefix_exactly_matches_legacy(self):
        self.assert_oracle(representative_history())

    def test_missing_columns_and_missing_close(self):
        hist = representative_history()
        self.assert_oracle(hist[["time", "close", "sentiment"]])
        self.assert_oracle(hist[["time", "sentiment"]])

    def test_nans_zeros_and_numeric_strings(self):
        hist = representative_history()
        for col in hist.columns.drop("time"):
            hist.loc[:10, col] = np.nan
            hist.loc[30:54, col] = 0
            hist.loc[[67, 99, 100, 160, 199, 239], col] = np.nan
            hist[col] = hist[col].astype(str)
            hist.loc[121, col] = "invalid"
        self.assert_oracle(hist)

    def test_all_nan_and_all_zero_close(self):
        for value in (np.nan, 0.0):
            hist = representative_history(220)
            hist["close"] = value
            self.assert_oracle(hist)

    def test_availability_counts_rows_not_valid_prices(self):
        hist = representative_history(220)
        hist.loc[:48, "close"] = np.nan
        result = self.assert_oracle(hist)
        for span in (50, 100, 200):
            self.assertFalse(result.loc[span - 2, f"has_ema{span}"])
            self.assertTrue(result.loc[span - 1, f"has_ema{span}"])

    def test_cross_window_includes_ten_transitions(self):
        hist = representative_history(240)
        result = self.assert_oracle(hist)
        e50 = hist.close.ewm(span=50, adjust=False).mean()
        e100 = hist.close.ewm(span=100, adjust=False).mean()
        diff = e50 - e100
        crosses = np.flatnonzero(((diff.shift(1) <= 0) & (diff > 0)).to_numpy())
        crosses = [idx for idx in crosses if 100 <= idx < len(hist) - 10]
        self.assertTrue(crosses)
        for idx in crosses:
            self.assertTrue(result.loc[idx, "ema50_cross_recent"])
            self.assertTrue(result.loc[idx + 9, "ema50_cross_recent"])
            self.assertFalse(result.loc[idx + 10, "ema50_cross_recent"])

    def test_cross_before_ema100_availability_is_not_discarded(self):
        hist = representative_history(220)
        hist["close"] = np.r_[np.full(20, 100.), np.full(74, 80.), np.full(126, 200.)]
        result = self.assert_oracle(hist)
        self.assertFalse(result.loc[98, "ema50_cross_recent"])
        self.assertTrue(result.loc[99, "ema50_cross_recent"])
        self.assertTrue(result.loc[104, "ema50_cross_recent"])
        self.assertFalse(result.loc[105, "ema50_cross_recent"])

    def test_infinities_match_legacy(self):
        hist = representative_history()
        for col in hist.columns.drop("time"):
            hist.loc[[15, 75, 153], col] = np.inf
            hist.loc[[31, 102], col] = -np.inf
        self.assert_oracle(hist)

    def test_acceleration_and_change_minimum_periods(self):
        hist = representative_history(40)
        result = self.assert_oracle(hist)
        self.assertTrue(pd.isna(result.loc[13, "social_accel"]))
        self.assertTrue(pd.notna(result.loc[14, "social_accel"]))
        self.assertTrue(pd.isna(result.loc[29, "price_change_30d"]))
        self.assertTrue(pd.notna(result.loc[30, "price_change_30d"]))
        # Three short-window values and eight shifted baseline values are
        # required independently, even when the total row count is sufficient.
        hist.loc[14:18, "posts_active"] = np.nan
        result = self.assert_oracle(hist)
        self.assertTrue(pd.isna(result.loc[20, "social_accel"]))
        self.assertTrue(pd.notna(result.loc[21, "social_accel"]))

    def test_index_labels_do_not_affect_computation(self):
        hist = representative_history(220)
        hist.index = pd.Index(np.arange(len(hist))[::-1] // 2, name="source_row")
        self.assert_oracle(hist)
        hist.index = pd.MultiIndex.from_arrays([np.arange(len(hist)) % 3, np.arange(len(hist)) % 7])
        self.assert_oracle(hist)

    def test_prefix_invariance_and_no_input_mutation(self):
        hist = representative_history()
        before = hist.copy(deep=True)
        full = historical_features(hist)
        for length in (10, 14, 15, 30, 31, 49, 50, 99, 100, 199, 200, 239):
            pd.testing.assert_frame_equal(historical_features(hist.iloc[:length]), full.iloc[:length - 9], check_exact=True)
        pd.testing.assert_frame_equal(hist, before, check_exact=True)

    def test_short_history_is_empty_with_schema(self):
        for length in (0, 1, 9):
            result = historical_features(representative_history(length))
            self.assertTrue(result.empty)
            self.assertEqual(list(result.columns), list(FEATURE_COLUMNS + EMA_COLUMNS))

    def test_missing_time_matches_legacy_failure(self):
        hist = representative_history(20).drop(columns="time")
        with self.assertRaises(KeyError):
            feature_row(hist)
        with self.assertRaises(KeyError):
            historical_features(hist)


if __name__ == "__main__":
    unittest.main()
