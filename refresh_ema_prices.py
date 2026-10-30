"""Refresh only explicitly verified exchange OHLCV pairs through last completed UTC day.

No synthetic candles, no ticker guesses, and no LunarCrush API requests.
A failed pair remains stale and therefore cannot qualify for EMA confirmation.
"""
import argparse
import csv
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def candle_day(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ValueError("Non-UTC candle")
    if (dt.hour, dt.minute, dt.second, dt.microsecond) != (0, 0, 0, 0):
        raise ValueError("Not a daily UTC candle")
    return dt.date()


def valid_ohlcv(row, pair, exchange):
    if row.get("pair") != pair or row.get("exchange") != exchange:
        raise ValueError("Exchange provenance mismatch")
    vals = [float(row[k]) for k in ("open", "high", "low", "close", "volume")]
    if not all(math.isfinite(v) for v in vals) or min(vals[:4]) <= 0 or vals[4] < 0:
        raise ValueError("Invalid OHLCV")
    o, h, l, c, _ = vals
    if h < max(o, c, l) or l > min(o, c, h):
        raise ValueError("Invalid candle envelope")
    return candle_day(row["time"])


def contiguous(data, end_day, minimum=300):
    days = sorted(data)
    if len(days) < minimum or days[-1] != end_day:
        return False
    return all((b - a).days == 1 for a, b in zip(days[-minimum:], days[-minimum + 1:]))


def refresh_pair(path, exchange, pair, market, required_day, max_backfill=40):
    """Validate existing archive then fetch missing completed candles only."""
    with path.open(newline="") as f:
        existing = list(csv.DictReader(f))
    if not existing:
        raise ValueError("Empty archive")
    candles = {}
    for row in existing:
        d = valid_ohlcv(row, pair, exchange)
        if d in candles:
            raise ValueError("Duplicate archived day")
        candles[d] = row
    latest = max(candles)
    if latest > required_day:
        # Future/partial candles are never taken into EMA analysis.
        raise ValueError("Archive contains future/partial day")
    if latest == required_day:
        if not contiguous(candles, required_day):
            raise ValueError("Archive has insufficient/gapped history")
        return 0
    gap = (required_day - latest).days
    if gap > max_backfill:
        raise ValueError("Archive too stale for bounded automatic refresh")
    since_ms = int(datetime.combine(latest + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
    limit = min(max(gap + 2, 5), 100)
    fetched = market.fetch_ohlcv(pair, timeframe="1d", since=since_ms, limit=limit)
    new_rows = {}
    for item in fetched:
        if len(item) < 6:
            continue
        moment = datetime.fromtimestamp(int(item[0])/1000, tz=timezone.utc)
        if moment.time() != datetime.min.time():
            continue
        d = moment.date()
        if d <= latest or d > required_day:
            continue
        row = {"time": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "open": str(item[1]), "high": str(item[2]), "low": str(item[3]),
               "close": str(item[4]), "volume": str(item[5]),
               "exchange": exchange, "pair": pair}
        valid_ohlcv(row, pair, exchange)
        new_rows[d] = row
    merged = {**candles, **new_rows}
    if not contiguous(merged, required_day):
        raise ValueError(f"Missing completed candles: have through {max(merged)}; require {required_day}")
    # Atomic replacement only after all freshness and continuity checks pass.
    fieldnames = ["time", "open", "high", "low", "close", "volume", "exchange", "pair"]
    selected = [merged[d] for d in sorted(merged)[-500:]]
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
        try:
            writer = csv.DictWriter(tmp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(selected)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
    os.replace(temp_path, path)
    return len(new_rows)


def refresh(data_dir=Path("data_price"), mapping_path=Path("config/symbol_map.json"),
            inventory_path=Path("reports/backfill_inventory.csv"), output=Path("reports/ema_refresh_latest.json"),
            today=None, exchange_factory=None):
    today = today or datetime.now(timezone.utc).date()
    required_day = today - timedelta(days=1)
    mapping = json.loads(Path(mapping_path).read_text())
    with Path(inventory_path).open(newline="") as f:
        inventory = list(csv.DictReader(f))
    # Exact one-to-one mapping to documented exchange and pair.
    records = {}
    for row in inventory:
        coin_id = str(row.get("coin_id", ""))
        if coin_id in records:
            raise ValueError("Duplicate coin ID in inventory")
        records[coin_id] = row
    if exchange_factory is None:
        import ccxt
        exchange_factory = lambda name: getattr(ccxt, name)({"enableRateLimit": True, "timeout": 30000})
    clients = {}
    results = []
    for coin_id, config in sorted(mapping.items(), key=lambda item: item[0]):
        record = records.get(str(coin_id))
        path = Path(data_dir) / f"{coin_id}.csv"
        item = {"coin_id": str(coin_id), "status": "STALE", "new_bars": 0, "reason": ""}
        try:
            if (record is None or record.get("exchange") != config.get("exchange")
                or record.get("pair") != config.get("pair")
                or record.get("status") not in ("ok", "partial")
                or record.get("gaps_detected") != "0" or not path.is_file()):
                raise ValueError("Unverified ID/exchange/pair or missing archive")
            exchange, pair = config["exchange"], config["pair"]
            if exchange not in clients:
                clients[exchange] = exchange_factory(exchange)
                clients[exchange].load_markets()
            client = clients[exchange]
            if pair not in client.markets or not client.has.get("fetchOHLCV"):
                raise ValueError("Verified pair unavailable at exchange")
            # Exact exchange pair is approved; never infer by ticker symbol.
            added = refresh_pair(path, exchange, pair, client, required_day)
            item.update(status="READY", new_bars=added)
        except Exception as exc:
            item["reason"] = f"{type(exc).__name__}: {exc}"[:240]
        results.append(item)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = {"as_of_utc": today.isoformat(),
               "required_completed_day": required_day.isoformat(),
               "checked": len(results), "ready": sum(x["status"] == "READY" for x in results),
               "stale": sum(x["status"] != "READY" for x in results), "assets": results}
    output.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Verified EMA refresh: {summary['ready']}/{summary['checked']} ready, {summary['stale']} stale")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data_price")
    parser.add_argument("--output", default="reports/ema_refresh_latest.json")
    args = parser.parse_args()
    refresh(data_dir=Path(args.data_dir), output=Path(args.output))
