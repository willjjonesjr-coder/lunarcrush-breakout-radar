#!/usr/bin/env python3
"""Import reviewed coin-ID-specific 500-day OHLCV candles from fixed 80-coin artifact.

No ticker-only fallback. Import is atomic at the validation stage; publish by CI.
"""
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ARTIFACT = Path("artifact-backfill")
APPROVED = {
    "6": ("BNB", "BNB", "kraken", "BNB/USD"),
    "3": ("XRP", "XRP", "kraken", "XRP/USD"),
    "12": ("TRON", "TRX", "kraken", "TRX/USD"),
    "26": ("Zcash", "ZEC", "kraken", "ZEC/USD"),
    "29": ("Dogecoin", "DOGE", "kraken", "DOGE/USD"),
    "18": ("Chainlink", "LINK", "kraken", "LINK/USD"),
    "11": ("Cardano", "ADA", "kraken", "ADA/USD"),
    "3377": ("Near Protocol", "NEAR", "kraken", "NEAR/USD"),
    "10": ("Stellar", "XLM", "kraken", "XLM/USD"),
    "5": ("Bitcoin Cash", "BCH", "kraken", "BCH/USD"),
    "4": ("Litecoin", "LTC", "kraken", "LTC/USD"),
    "2545": ("Avalanche", "AVAX", "kraken", "AVAX/USD"),
    "70056": ("Sui", "SUI", "kraken", "SUI/USD"),
    "84657": ("Bittensor", "TAO", "kraken", "TAO/USD"),
    "3378": ("Injective", "INJ", "kraken", "INJ/USD"),
    "1813": ("Filecoin", "FIL", "kraken", "FIL/USD"),
    "169": ("Fetch", "FET", "kraken", "FET/USD"),
    "152389": ("Virtuals Protocol", "VIRTUAL", "kraken", "VIRTUAL/USD"),
    "13238": ("Pendle", "PENDLE", "kraken", "PENDLE/USD"),
    "146377": ("Aerodrome", "AERO", "kraken", "AERO/USD"),
    "110579": ("Pepe", "PEPE", "kraken", "PEPE/USD"),
}
FIELDS = ["coin_id", "status", "exchange", "pair", "bars_fetched",
          "earliest_time", "latest_time", "gaps_detected", "reason"]


def rows(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def check_history(path, exchange, pair):
    candles = rows(path)
    if len(candles) != 500:
        raise ValueError(f"{path}: 500 daily bars required, got {len(candles)}")
    dates = []
    for c in candles:
        if c.get("exchange") != exchange or c.get("pair") != pair:
            raise ValueError(f"{path}: exchange/pair mismatch")
        day = datetime.fromisoformat(c["time"].replace("Z", "+00:00"))
        if day.tzinfo is None or day.utcoffset().total_seconds() != 0 or day.hour or day.minute or day.second:
            raise ValueError(f"{path}: invalid daily UTC timestamp")
        for field in ("open", "high", "low", "close"):
            if float(c[field]) <= 0:
                raise ValueError(f"{path}: invalid OHLC")
        if float(c["high"]) < max(float(c["open"]), float(c["close"])) or float(c["low"]) > min(float(c["open"]), float(c["close"])):
            raise ValueError(f"{path}: invalid high-low envelope")
        dates.append(day.date())
    if dates[-1].isoformat() != "2026-10-28" or len(dates) != len(set(dates)):
        raise ValueError(f"{path}: wrong observation period or duplicates")
    if any((b - a).days != 1 for a, b in zip(dates, dates[1:])):
        raise ValueError(f"{path}: missing or unordered dates")


def main():
    latest = {str(r["id"]): (r["name"], r["symbol"].upper())
              for r in rows(Path("reports/breakout_radar.csv"))
              if r.get("id") and r.get("symbol") and r.get("name")}
    incoming = {r["coin_id"]: r for r in rows(ARTIFACT / "reports/backfill_inventory.csv")}
    mapping_path = Path("config/symbol_map.json")
    existing_map = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    inventory_path = Path("reports/backfill_inventory.csv")
    old_rows = {r["coin_id"]: r for r in rows(inventory_path)} if inventory_path.exists() else {}
    for id, (name, symbol, exchange, pair) in APPROVED.items():
        if latest.get(id) != (name, symbol):
            raise ValueError(f"{id}: LunarCrush identity mismatch: {latest.get(id)} vs {(name, symbol)}")
        row = incoming.get(id)
        if row is None or any((row.get(k) != v) for k, v in (
            ("status", "ok"), ("exchange", exchange), ("pair", pair),
            ("bars_fetched", "500"), ("gaps_detected", "0"))):
            raise ValueError(f"{id}: inventory not verified for {exchange} {pair}")
        prior = existing_map.get(id)
        if prior and prior != {"exchange": exchange, "pair": pair}:
            raise ValueError(f"{id}: conflicts with existing verified mapping")
        check_history(ARTIFACT / "data_price" / f"{id}.csv", exchange, pair)
    # All approvals complete: copy only selected, verified IDs.
    output = Path("data_price")
    output.mkdir(exist_ok=True)
    for id, (_, _, exchange, pair) in APPROVED.items():
        shutil.copyfile(ARTIFACT / "data_price" / f"{id}.csv", output / f"{id}.csv")
        existing_map[id] = {"exchange": exchange, "pair": pair}
        old_rows[id] = incoming[id]
    mapping_path.write_text(json.dumps(existing_map, sort_keys=True, indent=2) + "\n")
    with inventory_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for id in sorted(old_rows, key=int):
            writer.writerow({k: old_rows[id].get(k, "") for k in FIELDS})
    print(f"Validated {len(APPROVED)} new histories; total mapped: {len(existing_map)}")


if __name__ == "__main__":
    main()
