#!/usr/bin/env python3
"""Fetch explicit BTC/ETH USD daily candles for the regime benchmark.

Symbols are intentionally verified as exchange market bases. IDs 'btc' and 'eth'
are synthetic benchmark keys, not LunarCrush IDs. Files are stored separately
from altcoin backfills. Never use BTC/ETH as candidates in the altcoin scanner.
"""
import argparse
from pathlib import Path
import pandas as pd

def fetch(output="data_price", bars=500):
    import ccxt
    ex = ccxt.kraken({"enableRateLimit": True, "timeout": 30000})
    ex.load_markets()
    target = {"btc": ("BTC", ["BTC/USD", "XBT/USD"]),
              "eth": ("ETH", ["ETH/USD"])}
    Path(output).mkdir(parents=True, exist_ok=True)
    inventory = []
    for key, (symbol, pairs) in target.items():
        pair = next((p for p in pairs if p in ex.markets and
                     ex.markets[p].get("base", "").upper() in
                     ({symbol, "XBT"} if symbol == "BTC" else {symbol})), None)
        if not pair:
            raise RuntimeError(f"No verified Kraken pair for {symbol}")
        now = int(pd.Timestamp.now(tz="UTC").normalize().timestamp() * 1000)
        since = now - (bars + 20) * 86400000
        candles = {}
        for _ in range(12):
            batch = ex.fetch_ohlcv(pair, timeframe="1d", since=since, limit=720)
            if not batch:
                break
            for row in batch:
                if row[0] < now:
                    candles[int(row[0])] = row
            nxt = int(batch[-1][0]) + 86400000
            if nxt <= since or nxt >= now:
                break
            since = nxt
        ordered = [candles[k] for k in sorted(candles)][-bars:]
        if len(ordered) < 200:
            raise RuntimeError(f"{symbol}: insufficient bars ({len(ordered)})")
        df = pd.DataFrame(ordered, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        df["exchange"], df["pair"] = "kraken", pair
        df = df[["time", "open", "high", "low", "close", "volume", "exchange", "pair"]]
        df.to_csv(Path(output) / f"{key}.csv", index=False)
        gaps = int((pd.to_datetime(df.time).diff().dt.total_seconds().dropna() > 86400).sum())
        inventory.append({"key": key, "symbol": symbol, "pair": pair,
                          "bars": len(df), "gaps": gaps,
                          "first": df.time.iloc[0], "last": df.time.iloc[-1]})
    return inventory

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data_price")
    p.add_argument("--bars", type=int, default=500)
    args = p.parse_args()
    rows = fetch(args.output, args.bars)
    pd.DataFrame(rows).to_csv("reports/btc_eth_inventory.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
