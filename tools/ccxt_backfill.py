#!/usr/bin/env python3
"""Public-API daily OHLCV backfill, kept separate from LunarCrush data.

Install: pip install ccxt pandas
Run: python tools/ccxt_backfill.py --top 20
Then: python tools/ccxt_backfill.py --top 80
"""
import argparse
import json
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

EXCHANGES = ("kraken", "coinbase", "binance")
QUOTE_ORDER = ("USD", "USDT")
EXCLUDED = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "WBTC", "WETH", "PAXG"}
FIELDS = ["coin_id", "status", "exchange", "pair", "bars_fetched", "earliest_time",
          "latest_time", "gaps_detected", "reason"]

def universe(data_dir, top):
    coins = []
    for p in Path(data_dir).glob("history_*.csv"):
        try:
            df = pd.read_csv(p, usecols=["market_cap"])
            cap = pd.to_numeric(df["market_cap"], errors="coerce").dropna()
            coins.append((p.stem.removeprefix("history_"), float(cap.iloc[-1]) if len(cap) else 0))
        except Exception:
            coins.append((p.stem.removeprefix("history_"), 0))
    return [c for c, _ in sorted(coins, key=lambda x: x[1], reverse=True)[:top]]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--bars", type=int, default=500)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--output-dir", default="data_price")
    ap.add_argument("--inventory", default="reports/backfill_inventory.csv")
    ap.add_argument("--symbol-map", default="config/symbol_map.json")
    ap.add_argument("--exchanges", default=",".join(EXCHANGES))
    args = ap.parse_args()
    import ccxt
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(filename="logs/backfill.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    mapping_file = Path(args.symbol_map)
    mapping = json.loads(mapping_file.read_text()) if mapping_file.exists() else {}
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    Path(args.inventory).parent.mkdir(parents=True, exist_ok=True)
    clients = {}
    for name in args.exchanges.split(","):
        name = name.strip()
        try:
            ex = getattr(ccxt, name)({"enableRateLimit": True, "timeout": 30000})
            ex.load_markets()
            clients[name] = ex
        except Exception as exc:
            logging.warning("Exchange %s unavailable: %s", name, exc)
    rows = []
    now = int(time.time() // 86400 * 86400 * 1000)  # only completed UTC candles
    for coin in universe(args.data_dir, args.top):
        record = dict.fromkeys(FIELDS, "")
        record["coin_id"] = coin
        if coin.upper() in EXCLUDED:
            record.update(status="excluded", reason="excluded asset")
            rows.append(record)
            continue
        # Explicit map format: {"coin-id":{"exchange":"kraken","pair":"FIL/USD"}}
        configured = mapping.get(coin)
        attempts = []
        if configured:
            attempts.append((configured["exchange"], configured["pair"]))
        else:
            # These are provisional ticker guesses; verify mapping before research use.
            ticker = coin.upper()
            for exchange in clients:
                for quote in QUOTE_ORDER:
                    attempts.append((exchange, f"{ticker}/{quote}"))
        error = "no supported verified mapping"
        for exchange, pair in attempts:
            ex = clients.get(exchange)
            if not ex or pair not in ex.markets or not ex.has.get("fetchOHLCV"):
                continue
            try:
                since = now - (args.bars + 15) * 86400000
                candles = {}
                for _ in range(15):
                    batch = ex.fetch_ohlcv(pair, timeframe="1d", since=since, limit=min(1000, args.bars + 15))
                    if not batch:
                        break
                    for c in batch:
                        if c[0] < now:
                            candles[int(c[0])] = c
                    nxt = int(batch[-1][0]) + 86400000
                    if nxt <= since or nxt >= now:
                        break
                    since = nxt
                ordered = [candles[k] for k in sorted(candles)][-args.bars:]
                if len(ordered) < 2:
                    error = f"{exchange} {pair}: insufficient candles"
                    continue
                df = pd.DataFrame(ordered, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["time"] = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                df["exchange"], df["pair"] = exchange, pair
                df = df[["time", "open", "high", "low", "close", "volume", "exchange", "pair"]]
                gaps = int((pd.to_datetime(df.time).diff().dt.total_seconds().dropna() > 86400).sum())
                df.to_csv(Path(args.output_dir) / f"{coin}.csv", index=False)
                record.update(status="ok" if len(df) >= args.bars else "partial",
                              exchange=exchange, pair=pair, bars_fetched=len(df),
                              earliest_time=df.time.iloc[0], latest_time=df.time.iloc[-1],
                              gaps_detected=gaps,
                              reason="ticker heuristic: review identity" if not configured else "")
                if not configured:
                    logging.warning("%s mapped heuristically to %s %s; identity review required", coin, exchange, pair)
                break
            except Exception as exc:
                error = f"{exchange} {pair}: {exc}"
                logging.warning("%s %s", coin, error)
                time.sleep(2)
        if not record["status"]:
            record.update(status="unresolved", reason=error)
        logging.info("%s %s %s %s", coin, record["status"], record["exchange"], record["bars_fetched"])
        rows.append(record)
        pd.DataFrame(rows, columns=FIELDS).to_csv(args.inventory, index=False)
    print(pd.DataFrame(rows).groupby("status").size().to_string())
    print("Inventory:", args.inventory)

if __name__ == "__main__":
    main()
