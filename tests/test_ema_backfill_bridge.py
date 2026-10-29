import csv
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from phase2_safeguards import resolve_ema_source, technical_confirmation


class BackfillBridgeTests(unittest.TestCase):
    def test_requires_explicit_id_mapping_and_matching_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            prices = root / "data_price"
            reports = root / "reports"
            config = root / "config"
            for d in (data, prices, reports, config):
                d.mkdir()
            mapping = config / "symbol_map.json"
            inventory = reports / "backfill_inventory.csv"
            price = prices / "123.csv"
            price.write_text("time,close,exchange,pair\n2026-10-27,100,kraken,FIL/USD\n")
            native = data / "history_123.csv"
            args = (123, data, prices, mapping, inventory)
            self.assertEqual(resolve_ema_source(*args)[0], native)
            mapping.write_text(json.dumps({"123": {"exchange": "kraken", "pair": "FIL/USD"}}))
            inventory.write_text("coin_id,status,exchange,pair,gaps_detected\n"
                                 "123,ok,kraken,FIL/USD,0\n")
            self.assertEqual(resolve_ema_source(*args), (price, "VERIFIED EXCHANGE MAPPING"))
            inventory.write_text("coin_id,status,exchange,pair,gaps_detected\n"
                                 "123,ok,binance,FIL/USDT,0\n")
            self.assertEqual(resolve_ema_source(*args)[0], native)

    def test_approved_exchange_csv_supplies_ema_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            price = Path(tmp) / "123.csv"
            today = date(2026, 10, 28)
            with price.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["time", "close", "exchange", "pair"])
                w.writeheader()
                for n in range(300, 0, -1):
                    w.writerow({"time": (today - timedelta(days=n)).isoformat(),
                                "close": 100 + (300 - n) * .3,
                                "exchange": "kraken", "pair": "FIL/USD"})
            self.assertEqual(technical_confirmation(price, today)["technical_status"],
                             "EMA CONFIRMED")


if __name__ == "__main__":
    unittest.main()
