import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from refresh_ema_prices import refresh_pair, refresh


class FakeMarket:
    has = {"fetchOHLCV": True}
    markets = {"BTC/USD": {"base": "BTC"}}
    def __init__(self, returned):
        self.returned = returned
        self.calls = 0
    def load_markets(self):
        return self.markets
    def fetch_ohlcv(self, pair, timeframe, since, limit):
        self.calls += 1
        return self.returned


def make_archive(path, end, count=500):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume", "exchange", "pair"])
        writer.writeheader()
        for n in range(count-1, -1, -1):
            day = end - timedelta(days=n)
            writer.writerow({"time": day.isoformat() + "T00:00:00Z",
                             "open": 100, "high": 102, "low": 99, "close": 101,
                             "volume": 10, "exchange": "kraken", "pair": "BTC/USD"})


class RefreshTests(unittest.TestCase):
    def test_refreshes_missing_day_and_ignores_today(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "1.csv"
            make_archive(p, date(2026, 10, 28))
            def ohlcv(d):
                ms = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
                return [ms, 102, 104, 100, 103, 14]
            market = FakeMarket([ohlcv(date(2026, 10, 29)), ohlcv(date(2026, 10, 30))])
            self.assertEqual(refresh_pair(p, "kraken", "BTC/USD", market, date(2026, 10, 29)), 1)
            self.assertEqual(refresh_pair(p, "kraken", "BTC/USD", market, date(2026, 10, 29)), 0)
            with p.open(newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 500)
            self.assertEqual(rows[-1]["time"], "2026-10-29T00:00:00Z")

    def test_missing_candle_never_generates_synthetic_bar(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "1.csv"
            make_archive(p, date(2026, 10, 28))
            before = p.read_text()
            market = FakeMarket([])
            with self.assertRaises(ValueError):
                refresh_pair(p, "kraken", "BTC/USD", market, date(2026, 10, 29))
            self.assertEqual(p.read_text(), before)

    def test_invalid_mapping_fails_closed_and_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            data = root / "price"
            data.mkdir()
            make_archive(data / "1.csv", date(2026, 10, 28))
            mapping = root / "mapping.json"
            mapping.write_text(json.dumps({"1": {"exchange": "kraken", "pair": "BTC/USD"}}))
            inventory = root / "inventory.csv"
            inventory.write_text("coin_id,status,exchange,pair,gaps_detected\n1,ok,binance,BTC/USDT,0\n")
            out = root / "refresh.json"
            result = refresh(data_dir=data, mapping_path=mapping,
                             inventory_path=inventory, output=out,
                             today=date(2026, 10, 30),
                             exchange_factory=lambda name: FakeMarket([]))
            self.assertEqual(result["ready"], 0)
            self.assertEqual(result["stale"], 1)
            self.assertEqual(json.loads(out.read_text())["checked"], 1)


if __name__ == "__main__":
    unittest.main()
