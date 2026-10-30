#!/usr/bin/env python3
"""Import vetted, coin-ID-specific 500-day OHLCV candles from fixed 80-coin artifact.

No ticker-only fallback. Import is atomic at the validation stage; publish by CI.
"""
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ARTIFACT = Path("artifact-backfill")
APPROVED = {
    "14226": ("Convex Finance", "CVX", "kraken", "CVX/USD"),
    "70741": ("StarkNet", "STRK", "kraken", "STRK/USD"),
    "15": ("Dash", "DASH", "kraken", "DASH/USD"),
    "12391": ("Internet Computer", "ICP", "kraken", "ICP/USD"),
    "42935": ("Floki", "FLOKI", "kraken", "FLOKI/USD"),
    "151267": ("Kamino", "KMNO", "kraken", "KMNO/USD"),
    "149030": ("SPX6900", "SPX", "kraken", "SPX/USD"),
    "52238": ("Kaspa", "KAS", "kraken", "KAS/USD"),
    "20": ("Tezos", "XTZ", "kraken", "XTZ/USD"),
    "149895": ("Ether.fi", "ETHFI", "kraken", "ETHFI/USD"),
    "159730": ("Venice Token", "VVV", "kraken", "VVV/USD"),
    "11880": ("Raydium", "RAY", "kraken", "RAY/USD"),
    "2917": ("Shiba Inu", "SHIB", "kraken", "SHIB/USD"),
    "19": ("Cosmos", "ATOM", "kraken", "ATOM/USD"),
    "90376": ("Flare", "FLR", "kraken", "FLR/USD"),
    "148569": ("Jito", "JTO", "kraken", "JTO/USD"),
    "1790": ("Terra Classic", "LUNC", "kraken", "LUNC/USD"),
    "9887": ("JasmyCoin", "JASMY", "kraken", "JASMY/USD"),
    "145271": ("Sei", "SEI", "kraken", "SEI/USD"),
    "159180": ("Pudgy Penguins", "PENGU", "kraken", "PENGU/USD"),
    "2222": ("THORChain", "RUNE", "kraken", "RUNE/USD"),
    "152283": ("Layerzero", "ZRO", "kraken", "ZRO/USD"),
    "830": ("Stacks", "STX", "kraken", "STX/USD"),
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
