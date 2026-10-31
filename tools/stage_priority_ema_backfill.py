#!/usr/bin/env python3
"""Stage OHLCV for prioritized unmapped assets; NEVER approve ticker-only matches.

Uses public CCXT prices, isolated from data_price and verified inventory. Each
row requires later identity/contract/network review before import.
"""
import argparse
import csv
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

EXCHANGES = ("kraken", "coinbase", "binance")
QUOTES = ("USD", "USDT")
FIELDS = ["coin_id", "symbol", "name", "market_cap_usd", "breakout_score",
          "status", "exchange", "pair", "bars", "latest_day", "reason"]
DENIED = {"USDT", "USDC", "DAI", "USDS", "USDE", "USDD", "USDP",
          "FDUSD", "TUSD", "WBTC", "WETH", "PAXG", "USDSUI"}

def inspect_candles(candles, required, bars):
    unique = {}
    for c in candles:
        if len(c) < 6:
            continue
        stamp = datetime.fromtimestamp(int(c[0]) / 1000, timezone.utc)
        if stamp.time() != datetime.min.time() or stamp.date() > required:
            continue
        vals = [float(v) for v in c[1:6]]
        if not all(math.isfinite(v) for v in vals):
            raise ValueError("non-finite OHLCV")
        o, h, l, close, volume = vals
        if min(o, h, l, close) <= 0 or volume < 0 or h < max(o, close) or l > min(o, close):
            raise ValueError("invalid OHLCV envelope")
        unique[stamp.date()] = [stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), *vals]
    days = sorted(unique)
    if len(days) < bars:
        return None, "fewer than requested candles"
    days = days[-bars:]
    if days[-1] != required:
        return None, "latest completed candle missing"
    if any((b - a).days != 1 for a, b in zip(days, days[1:])):
        return None, "daily candle gaps"
    return [unique[d] for d in days], ""

def run(queue_path, output_dir, count=80, bars=500):
    import ccxt
    batch = json.loads(Path(queue_path).read_text())["first_review_batch"][:count]
    output_dir.mkdir(parents=True, exist_ok=True)
    clients = {}
    results = []
    required = datetime.now(timezone.utc).date() - timedelta(days=1)
    for coin in batch:
        symbol = str(coin["symbol"]).upper()
        record = {k: "" for k in FIELDS}
        record.update(coin_id=str(coin["coin_id"]), symbol=symbol, name=coin["name"],
                      market_cap_usd=coin["market_cap_usd"], breakout_score=coin["breakout_score"],
                      status="UNVERIFIED", reason="No validated 500-day daily history")
        if symbol in DENIED:
            record.update(status="SKIPPED", reason="stablecoin/wrapped asset; identity review needed")
            results.append(record)
            continue
        for exchange in EXCHANGES:
            if record["status"] == "STAGED":
                break
            try:
                if exchange not in clients:
                    client = getattr(ccxt, exchange)({"enableRateLimit": True, "timeout": 30000})
                    client.load_markets()
                    clients[exchange] = client
                client = clients[exchange]
            except Exception as exc:
                record["reason"] = "exchange unavailable: " + str(exc)[:120]
                continue
            for quote in QUOTES:
                pair = symbol + "/" + quote
                if pair not in client.markets or not client.has.get("fetchOHLCV"):
                    continue
                try:
                    market = client.markets[pair]
                    if str(market.get("base", "")).upper() != symbol or market.get("spot") is False:
                        continue
                    start = int((required - timedelta(days=bars + 20)).strftime("%s")) * 1000
                    found = {}
                    for _ in range(16):
                        chunk = client.fetch_ohlcv(pair, timeframe="1d", since=start, limit=min(720, bars + 25))
                        if not chunk:
                            break
                        for candle in chunk:
                            found[int(candle[0])] = candle
                        following = int(chunk[-1][0]) + 86400000
                        if following <= start:
                            break
                        start = following
                        if datetime.fromtimestamp(start / 1000, timezone.utc).date() > required:
                            break
                    ready, why = inspect_candles(list(found.values()), required, bars)
                    if ready is None:
                        record["reason"] = exchange + " " + pair + ": " + why
                        continue
                    output = output_dir / (record["coin_id"] + ".csv")
                    with output.open("w", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow(["time", "open", "high", "low", "close", "volume", "exchange", "pair"])
                        writer.writerows([*v, exchange, pair] for v in ready)
                    record.update(status="STAGED", exchange=exchange, pair=pair,
                                  bars=len(ready), latest_day=required.isoformat(),
                                  reason="PROVISIONAL SYMBOL MATCH ONLY; verify contract/network and LunarCrush coin ID")
                    break
                except Exception as exc:
                    record["reason"] = exchange + " " + pair + ": " + str(exc)[:110]
        results.append(record)
        print(record["coin_id"], symbol, record["status"], flush=True)
    with (output_dir / "review_results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(results)
    summary = {"required_day": required.isoformat(), "requested": len(batch),
               "staged_provisional": sum(r["status"] == "STAGED" for r in results),
               "approved": 0, "production_imports": 0,
               "policy": "Manual identity verification required; staged data may not be used for EMA confirmation."}
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(summary)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default="reports/ema_expansion_review_queue.json")
    parser.add_argument("--output", default="staging/ema_backfill_80")
    parser.add_argument("--count", type=int, default=80)
    parser.add_argument("--bars", type=int, default=500)
    a = parser.parse_args()
    run(a.queue, Path(a.output), a.count, a.bars)
