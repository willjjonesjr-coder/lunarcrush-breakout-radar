#!/usr/bin/env python3
"""Research-only expanded centralized-exchange coverage audit.

Never writes data_price/, symbol maps, approved inventory, scores or alerts.
A spot symbol/pair match is a DISCOVERY result, not an identity verification.
"""
import argparse
import csv
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXCHANGES = ("kraken", "coinbase", "binance", "okx", "bybit", "bitget", "gate", "mexc", "kucoin")
QUOTES = ("USD", "USDT", "USDC")
FIELDS = ("review_rank", "coin_id", "symbol", "name", "breakout_score",
          "exchange", "market_id", "pair", "quote", "spot", "active",
          "market_status", "history_status", "bars_available", "earliest_day",
          "latest_day", "gaps", "reason", "identity_status", "approval_status")
SKIP_SYMBOLS = {"USDT", "USDC", "DAI", "USDE", "USDS", "FDUSD", "TUSD", "WBTC", "WETH"}


def validate_bars(candles, required_day, minimum=300, preferred=500):
    """Return observed contiguous completed UTC suffix, without fabricating bars."""
    by_day = {}
    for c in candles:
        if len(c) < 6:
            return {"status": "INVALID_OHLCV", "bars": 0, "reason": "short candle"}
        try:
            ts = int(c[0])
            o, h, l, close, vol = [float(v) for v in c[1:6]]
        except (TypeError, ValueError, OverflowError):
            return {"status": "INVALID_OHLCV", "bars": 0, "reason": "invalid numeric candle"}
        if ts % 86400000 != 0:
            return {"status": "INVALID_OHLCV", "bars": 0, "reason": "non-UTC day"}
        day = datetime.fromtimestamp(ts / 1000, timezone.utc).date()
        if day > required_day:
            continue  # reject current unfinished candle
        if not all(math.isfinite(v) for v in (o, h, l, close, vol)) or min(o, h, l, close) <= 0 or vol < 0 or h < max(o, close, l) or l > min(o, close, h):
            return {"status": "INVALID_OHLCV", "bars": 0, "reason": "OHLCV envelope"}
        values = (o, h, l, close, vol)
        if day in by_day and by_day[day] != values:
            return {"status": "INVALID_OHLCV", "bars": 0, "reason": "conflicting duplicate"}
        by_day[day] = values
    days = sorted(by_day)
    if not days:
        return {"status": "NO_CANDLES", "bars": 0, "reason": "no completed bars"}
    suffix = [days[-1]]
    for d in reversed(days[:-1]):
        if (suffix[-1] - d).days != 1:
            break
        suffix.append(d)
    bars = len(suffix)
    latest = days[-1]
    status = ("STALE" if latest != required_day else
              "500_BAR_READY_PROVISIONAL" if bars >= preferred else
              "300_BAR_READY_PROVISIONAL" if bars >= minimum else
              "SHORT_HISTORY")
    return {"status": status, "bars": bars, "earliest": suffix[-1].isoformat(),
            "latest": latest.isoformat(), "gaps": len(days) - bars,
            "reason": "Ticker/pair match only; verify independent asset identity"}


def markets_for_coin(client, symbol, quotes=QUOTES):
    """Inspect exact CCXT base/quote fields; never infer identity from ticker."""
    matches = []
    for market in client.markets.values():
        if str(market.get("base") or "").upper() != symbol:
            continue
        if str(market.get("quote") or "").upper() not in quotes:
            continue
        if market.get("spot") is not True:
            continue
        if market.get("active") is False:
            continue
        matches.append(market)
    quote_order = {q: i for i, q in enumerate(quotes)}
    return sorted(matches, key=lambda m: (quote_order.get(str(m.get("quote")).upper(), 99), str(m.get("symbol"))))


def fetch_candles(client, market, required_day, bars):
    if client.has.get("fetchOHLCV") is not True:
        return {"status": "OHLCV_UNSUPPORTED", "bars": 0, "reason": "exchange has no fetchOHLCV"}
    since_day = required_day - timedelta(days=bars + 25)
    since = int(datetime.combine(since_day, datetime.min.time(), timezone.utc).timestamp() * 1000)
    collected = []
    for _ in range(12):
        batch = client.fetch_ohlcv(market["symbol"], "1d", since=since, limit=min(720, bars + 25))
        if not batch:
            break
        collected.extend(batch)
        next_since = max(int(c[0]) for c in batch) + 86400000
        if next_since <= since:
            break
        since = next_since
        if datetime.fromtimestamp(since / 1000, timezone.utc).date() > required_day:
            break
    return validate_bars(collected, required_day, preferred=bars)


def audit(queue, clients, required_day, max_pairs=2, bars=500):
    rows = []
    for coin in queue:
        symbol = str(coin.get("symbol") or "").strip().upper()
        base = {k: str(coin.get(k, "")) for k in ("review_rank", "coin_id", "symbol", "name", "breakout_score")}
        base["symbol"] = symbol
        def record(exchange, **items):
            r = dict.fromkeys(FIELDS, "")
            r.update(base)
            r.update(exchange=exchange, identity_status="UNVERIFIED_SYMBOL_MATCH_ONLY",
                     approval_status="RESEARCH_ONLY_DO_NOT_IMPORT")
            r.update(items)
            rows.append(r)
        if not symbol or symbol in SKIP_SYMBOLS:
            record("", market_status="EXCLUDED", history_status="NOT_CHECKED",
                   reason="excluded or missing base symbol")
            continue
        for exchange, result in clients.items():
            if isinstance(result, Exception):
                record(exchange, market_status="EXCHANGE_UNAVAILABLE", history_status="NOT_CHECKED",
                       reason=str(result)[:160])
                continue
            matches = markets_for_coin(result, symbol)
            if not matches:
                record(exchange, market_status="NO_EXACT_SPOT_PAIR", history_status="NOT_CHECKED",
                       reason="no exact active spot base with USD/USDT/USDC quote")
                continue
            for i, market in enumerate(matches):
                pair = str(market.get("symbol") or "")
                detail = dict(market_id=str(market.get("id") or ""), pair=pair,
                              quote=str(market.get("quote") or ""), spot=True,
                              active=market.get("active"), market_status="FOUND_PROVISIONAL")
                if i >= max_pairs:
                    record(exchange, **detail, history_status="NOT_SAMPLED",
                           reason="maximum OHLCV samples per exchange reached")
                    continue
                try:
                    outcome = fetch_candles(result, market, required_day, bars)
                    record(exchange, **detail, history_status=outcome["status"],
                           bars_available=outcome.get("bars", 0),
                           earliest_day=outcome.get("earliest", ""),
                           latest_day=outcome.get("latest", ""),
                           gaps=outcome.get("gaps", ""),
                           reason=outcome.get("reason", ""))
                except Exception as exc:
                    record(exchange, **detail, history_status="OHLCV_ERROR",
                           reason=(type(exc).__name__ + ": " + str(exc))[:160])
    return rows


def summarize(rows, requested):
    ids = {str(r["coin_id"]) for r in rows}
    coverage = {"no_market": 0, "spot_found": 0, "history_300_plus": 0,
                "short_history": 0, "exchange_or_api_error_only": 0}
    for cid in ids:
        group = [r for r in rows if str(r["coin_id"]) == cid]
        statuses = {r["history_status"] for r in group}
        found = any(r["market_status"] == "FOUND_PROVISIONAL" for r in group)
        if not found:
            coverage["no_market"] += 1
        else:
            coverage["spot_found"] += 1
        if statuses & {"300_BAR_READY_PROVISIONAL", "500_BAR_READY_PROVISIONAL"}:
            coverage["history_300_plus"] += 1
        if "SHORT_HISTORY" in statuses:
            coverage["short_history"] += 1
        if found and not (statuses & {"300_BAR_READY_PROVISIONAL", "500_BAR_READY_PROVISIONAL", "SHORT_HISTORY"}) and ("OHLCV_ERROR" in statuses or "OHLCV_UNSUPPORTED" in statuses):
            coverage["exchange_or_api_error_only"] += 1
    return {"requested_candidates": requested, "reported_candidates": len(ids),
            "exchange_rows": len(rows), "coverage": coverage,
            "approved": 0, "production_imports": 0,
            "policy": "Spot listing and even 500 clean candles are provisional until independent identity, provenance and liquidity verification. No production writes."}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--queue", default="reports/ema_expansion_review_queue.json")
    p.add_argument("--count", type=int, default=80)
    p.add_argument("--bars", type=int, default=500)
    p.add_argument("--max-pairs-per-exchange", type=int, default=2)
    p.add_argument("--exchanges", default=",".join(EXCHANGES))
    p.add_argument("--output", default="reports/expanded_cex_coverage")
    args = p.parse_args()
    if not 1 <= args.count <= 80 or args.bars < 300 or not 1 <= args.max_pairs_per_exchange <= 5:
        p.error("count must be 1-80, bars >=300, and max pairs 1-5")
    queue = json.loads(Path(args.queue).read_text())["first_review_batch"][:args.count]
    import ccxt
    clients = {}
    names = [x.strip() for x in args.exchanges.split(",") if x.strip()]
    for name in names:
        try:
            client = getattr(ccxt, name)({"enableRateLimit": True, "timeout": 15000})
            client.load_markets()
            clients[name] = client
        except Exception as exc:
            clients[name] = exc
    required_day = datetime.now(timezone.utc).date() - timedelta(days=1)
    rows = audit(queue, clients, required_day, args.max_pairs_per_exchange, args.bars)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix(".csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {"as_of_utc": datetime.now(timezone.utc).isoformat(),
               "completed_day": required_day.isoformat(),
               "exchanges_attempted": names,
               **summarize(rows, len(queue))}
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
