#!/usr/bin/env python3
"""Persist only pre-reviewed, explicitly identified exchange histories.

Never infer identity from ticker alone. Artifact must be an exact known run.
"""
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

# LunarCrush coin ID -> canonical name, symbol, exchange, market.
APPROVED = {
    "1": ("Bitcoin", "BTC", "kraken", "BTC/USD"),
    "2": ("Ethereum", "ETH", "kraken", "ETH/USD"),
    "3079": ("Solana", "SOL", "kraken", "SOL/USD"),
}
ARTIFACT = Path("artifact-backfill")
REPO = Path(".")


def rows(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def verify_candles(path, exchange, pair):
    candles = rows(path)
    if len(candles) != 500:
        raise ValueError(f"{path}: expected exactly 500 bars; got {len(candles)}")
    dates = []
    for c in candles:
        if c.get("exchange") != exchange or c.get("pair") != pair:
            raise ValueError(f"{path}: unexpected exchange/pair")
        timestamp = datetime.fromisoformat(c["time"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
            raise ValueError(f"{path}: timestamp must be UTC")
        if timestamp.time().isoformat() != "00:00:00":
            raise ValueError(f"{path}: non-daily candle")
        if float(c["close"]) <= 0 or float(c["open"]) <= 0:
            raise ValueError(f"{path}: invalid OHLC price")
        dates.append(timestamp.date())
    if len(dates) != len(set(dates)) or any((b - a).days != 1 for a, b in zip(dates, dates[1:])):
        raise ValueError(f"{path}: duplicate/gapped/out-of-order candles")
    if dates[-1].isoformat() != "2026-10-28":
        raise ValueError(f"{path}: unexpected artifact observation date")
    return len(dates)


def main():
    # Use a reviewed identity in the existing radar file, plus exact exchange metadata.
    identity = {str(r["id"]): (r["name"], r["symbol"].upper())
                for r in rows(REPO / "reports/breakout_radar.csv")
                if r.get("id") and r.get("symbol") and r.get("name")}
    inventory = {r["coin_id"]: r for r in rows(ARTIFACT / "reports/backfill_inventory.csv")}
    verified = []
    source = ARTIFACT / "data_price"
    for coin_id, (name, symbol, exchange, pair) in APPROVED.items():
        if identity.get(coin_id) != (name, symbol):
            raise ValueError(f"{coin_id}: LunarCrush identity does not match approval")
        record = inventory.get(coin_id)
        if not record or record.get("status") != "ok" or record.get("exchange") != exchange or record.get("pair") != pair:
            raise ValueError(f"{coin_id}: backfill inventory differs from approved exchange pair")
        if record.get("gaps_detected") != "0" or record.get("bars_fetched") != "500":
            raise ValueError(f"{coin_id}: backfill inventory coverage is incomplete")
        file = source / f"{coin_id}.csv"
        verify_candles(file, exchange, pair)
        verified.append((coin_id, exchange, pair, record))
    # Copy only AFTER every approval passes, so an invalid artifact fails closed.
    dest = REPO / "data_price"
    dest.mkdir(exist_ok=True)
    for coin_id, _, _, _ in verified:
        shutil.copyfile(source / f"{coin_id}.csv", dest / f"{coin_id}.csv")
    mapping_path = REPO / "config/symbol_map.json"
    current = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    for coin_id, exchange, pair, _ in verified:
        current[coin_id] = {"exchange": exchange, "pair": pair}
    mapping_path.write_text(json.dumps(current, sort_keys=True, indent=2) + "\n")
    fields = ["coin_id", "status", "exchange", "pair", "bars_fetched", "earliest_time",
              "latest_time", "gaps_detected", "reason"]
    inv_path = REPO / "reports/backfill_inventory.csv"
    with inv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for _, _, _, record in verified:
            writer.writerow({k: record.get(k, "") for k in fields})
    print(f"Approved {len(verified)} coin-ID histories: " + ", ".join(x[0] for x in verified))


if __name__ == "__main__":
    main()
