import unittest
import numpy as np
import pandas as pd
from market_regime import regime, classify, score_centered

class MarketRegimeTests(unittest.TestCase):
    def make_prices(self, slope=0.002):
        dates = pd.date_range("2024-01-01", periods=280, tz="UTC", freq="D")
        prices = {}
        for idx, sym in enumerate(["BTC", "ETH"] + [f"ALT{i}" for i in range(12)]):
            c = 100 * np.exp(np.arange(len(dates)) * slope * (1 + idx * .01))
            prices[str(idx)] = ({"symbol": sym, "name": sym},
                                pd.DataFrame({"close": c, "volume": np.full(len(c), 1000.)}, index=dates))
        return prices

    def test_bullish_and_bearish(self):
        bull = regime(self.make_prices(.003))
        bear = regime(self.make_prices(-.003))
        self.assertGreater(bull.iloc[-1].score, 60)
        self.assertLess(bear.iloc[-1].score, 40)
        self.assertEqual(bull.iloc[-1].breadth_assets, 14)

    def test_no_lookahead(self):
        prices = self.make_prices()
        original = regime(prices)
        for _, (_, df) in prices.items():
            df.loc[df.index[-1], "close"] *= 5
        revised = regime(prices)
        pd.testing.assert_series_equal(original.score.iloc[:-1], revised.score.iloc[:-1])

    def test_requires_btc_eth(self):
        prices = self.make_prices()
        prices.pop("0")
        with self.assertRaises(ValueError):
            regime(prices)

    def test_missing_breadth(self):
        self.assertTrue(regime(self.make_prices(), min_breadth=30).empty)

    def test_range(self):
        self.assertEqual(score_centered(-1000, .1), 10.)
        self.assertEqual(classify(50, 10), "consolidation")

if __name__ == "__main__":
    unittest.main()
