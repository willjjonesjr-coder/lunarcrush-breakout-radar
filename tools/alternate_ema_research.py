"""Research-only exchange coverage for score-qualified coins without a current EMA."""
import argparse
import csv
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from provisional_ema import API, fetch_history, match_identities, normalized, provisional_technicals
from tools.audit_expanded_cex_coverage import markets_for_coin
from tools.build_combined_ema_shortlist import unique

# Explicitly scoped to spot; CoinGecko identifiers are not exchange display names.
VENUES = {"coinbase": "gdax", "binance": "binance", "okx": "okex",
          "bybit": "bybit_spot", "bitget": "bitget", "gate": "gate",
          "mexc": "mxc", "kucoin": "kucoin"}
QUOTES = ("USD", "USDT", "USDC")
TOLERANCE = .02
CHECK_DAYS = 3


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def refs(path, cid, days):
    prices = {}
    for row in read_csv(path):
        dt = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() != timedelta(0) or dt.time() != datetime.min.time():
            continue
        d = dt.date()
        if d not in days:
            continue
        price = float(row["close"])
        if row.get("coin_id") != cid or price <= 0 or not isfinite(price) or d in prices:
            raise ValueError("Invalid or duplicate LunarCrush close")
        prices[d] = price
    if prices.keys() != set(days):
        raise ValueError("Missing exact LunarCrush UTC closes")
    return prices


def pair_quotes(tickers, identity, market_id):
    result = set()
    for t in tickers:
        if (t.get("market") or {}).get("identifier") != market_id:
            continue
        if normalized(t.get("base")) != normalized(identity["symbol"]):
            continue
        target = str(t.get("target") or "").upper()
        if target not in QUOTES:
            continue
        if t.get("coin_id") and t["coin_id"] != identity["coingecko_id"]:
            raise ValueError("Conflicting CoinGecko asset on exchange pair")
        if (t.get("coin_id") == identity["coingecko_id"] and t.get("is_stale") is False
                and t.get("is_anomaly") is False):
            result.add(target)
    return result


def audit(shortlist, production, closed_day, history_dir, registry, get, factory,
          history_fetch=fetch_history):
    targets = [r for r in unique(shortlist, "coin_id").values()
               if r["shortlist_status"] == "RESEARCH_CANDIDATE" and r["ema_status"] == "EMA NOT EVALUATED"]
    if not targets:
        return []
    unique(production, "id")
    results, clients = [], {}
    try:
        catalog = get("/coins/list?include_platform=true")
        if not isinstance(catalog, list) or not catalog:
            raise ValueError("Missing CoinGecko catalog")
        matches = match_identities(production, catalog, registry)
    except Exception as exc:
        return [dict(coin_id=r["coin_id"], status="COINGECKO_CATALOG_UNAVAILABLE",
                     error=str(exc)[:200]) for r in targets]

    def client(venue):
        if venue not in clients:
            try:
                c = factory(venue)
                c.load_markets()
                if not c.markets:
                    raise ValueError("Empty market catalog")
                clients[venue] = c
            except Exception as exc:
                clients[venue] = exc
        if isinstance(clients[venue], Exception):
            raise clients[venue]
        return clients[venue]

    days = [closed_day - timedelta(days=i) for i in reversed(range(CHECK_DAYS))]
    for r in targets:
        cid, symbol = r["coin_id"], r["symbol"]
        out = dict(coin_id=cid, symbol=symbol, name=r["name"],
                   closed_day=closed_day.isoformat(), attempts=[], status="NO_USABLE_ALTERNATE")
        results.append(out)
        try:
            k = client("kraken")
            out["kraken_usd_spot"] = ("PRESENT" if any(m.get("active") is True for m in
                markets_for_coin(k, symbol.upper(), QUOTES)) else "NO_ACTIVE_EXACT_PAIR")
        except Exception:
            out["kraken_usd_spot"] = "UNKNOWN"
        identity = matches.get(cid, {})
        if identity.get("status") != "MATCHED PROVISIONALLY":
            out.update(status="IDENTITY_REVIEW", error=identity.get("reason", "Missing asset match"))
            continue
        cg = identity["coingecko_id"]
        out["coingecko_id"] = cg
        try:
            reference = refs(history_dir / f"history_{cid}.csv", cid, days)
        except (OSError, KeyError, ValueError) as exc:
            out.update(status="REFERENCE_UNAVAILABLE", error=str(exc)[:200])
            continue
        try:
            endpoint = "/coins/" + quote(cg, safe="") + "/tickers"
            tickers = []
            for page in range(1, 4):
                batch = get(endpoint if page == 1 else f"{endpoint}?page={page}")["tickers"]
                if not isinstance(batch, list):
                    raise ValueError("Invalid CoinGecko ticker list")
                tickers.extend(batch)
                if len(batch) < 100:
                    break
            else:
                out["listing_scan_truncated"] = True
            quotes = {v: pair_quotes(tickers, identity, g) for v, g in VENUES.items()}
        except ValueError as exc:
            out.update(status="IDENTITY_OR_LISTING_REVIEW", error=str(exc)[:200])
            continue
        except Exception as exc:
            out.update(status="COINGECKO_TICKERS_UNAVAILABLE", error=str(exc)[:200])
            continue

        passing = []
        for venue, available in quotes.items():
            for q in (q for q in QUOTES if q in available):
                pair = symbol.upper() + "/" + q
                attempt = dict(exchange=venue, pair=pair)
                out["attempts"].append(attempt)
                try:
                    c = client(venue)
                except Exception as exc:
                    attempt.update(status="EXCHANGE_UNAVAILABLE", reason=str(exc)[:200])
                    continue
                try:
                    candles = history_fetch(c, pair, closed_day, 300)
                    closes = {date.fromisoformat(x[0][:10]): x[4] for x in candles[-CHECK_DAYS:]}
                    if closes.keys() != reference.keys():
                        raise ValueError("Alternate UTC candle dates do not match reference")
                    diffs = [abs(closes[d] / reference[d] - 1) for d in days]
                    attempt["comparison"] = [
                        dict(day=d.isoformat(), lunarcrush_close=reference[d], exchange_close=closes[d],
                             absolute_difference_pct=round(delta * 100, 6))
                        for d, delta in zip(days, diffs)]
                    if any(v > TOLERANCE + 1e-12 for v in diffs):
                        attempt["status"] = "PRICE_DISAGREEMENT"
                        continue
                    attempt["status"] = "CORROBORATED"
                    passing.append((venue, pair, provisional_technicals(candles)))
                except Exception as exc:
                    attempt.update(status="HISTORY_UNAVAILABLE", reason=str(exc)[:200])
        out["disagreement"] = any(a["status"] == "PRICE_DISAGREEMENT" for a in out["attempts"])
        if passing:
            venue, pair, tech = passing[0]
            count = len({p[0] for p in passing})
            out.update(status="CORROBORATED", exchange=venue, pair=pair,
                       corroborating_venues=count, technical_status=tech["provisional_technical_status"],
                       **{f"ema{n}": tech[f"provisional_ema{n}"] for n in (50, 100, 200)})
    return results


def get_coingecko(path):
    headers = {"Accept": "application/json", "User-Agent": "radar-alternate-research/1.0"}
    key = os.environ.get("COINGECKO_DEMO_API_KEY")
    if key:
        headers["x-cg-demo-api-key"] = key
    time.sleep(2)
    for attempt in range(2):
        try:
            with urlopen(Request(API + path, headers=headers), timeout=20) as response:
                return json.load(response)
        except (URLError, TimeoutError) as exc:
            transient = not isinstance(exc, HTTPError) or exc.code in {429, 500, 502, 503, 504}
            if attempt or not transient:
                raise
            time.sleep(12 if isinstance(exc, HTTPError) and exc.code == 429 else 3)


def public_json(url):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "radar-alternate-research/1.0"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


class GateSpot:
    """Use the spot-only public endpoints; no margin catalog is required."""
    root = "https://api.gateio.ws/api/v4/spot/"
    has = {"fetchOHLCV": True}

    def load_markets(self):
        self.markets = {}
        for row in public_json(self.root + "currency_pairs"):
            base, q = row["base"], row["quote"]
            symbol = f"{base}/{q}"
            self.markets[symbol] = dict(id=row["id"], base=base, quote=q, symbol=symbol,
                                        spot=True, active=row["trade_status"] == "tradable")

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        if timeframe != "1d":
            raise ValueError("Only daily UTC Gate candles are supported")
        params = urlencode(dict(currency_pair=self.markets[symbol]["id"], interval=timeframe,
                               **{"from": since // 1000, "to": since // 1000 + (limit - 1) * 86400}))
        data = public_json(self.root + "candlesticks?" + params)
        if not isinstance(data, list):
            raise ValueError("Unexpected Gate candle response")
        # Gate: time, quote volume, close, high, low, open, base volume, closed.
        return [[int(r[0]) * 1000, *map(float, (r[5], r[3], r[4], r[2], r[6]))]
                for r in data if str(r[7]).lower() == "true"]


class KrakenSpot:
    """Kraken is checked for coverage, not used for the alternate price series."""
    def load_markets(self):
        data = public_json("https://api.kraken.com/0/public/AssetPairs")
        if data["error"]:
            raise ValueError("Kraken spot catalog returned an error")
        self.markets = {}
        for row in data["result"].values():
            symbol = row.get("wsname", "")
            base, sep, q = symbol.partition("/")
            if sep:
                self.markets[symbol] = dict(base=base, quote=q, symbol=symbol, spot=True,
                                            active=row.get("status") == "online")


def spot_client(venue):
    if venue == "gate":
        return GateSpot()
    if venue == "kraken":
        return KrakenSpot()
    import ccxt
    kind = "coinbaseexchange" if venue == "coinbase" else venue
    c = getattr(ccxt, kind)({"enableRateLimit": True, "timeout": 12000, "trust_env": True,
                             "options": {"defaultType": "spot"}})
    c.has["fetchCurrencies"] = False  # Only spot markets are used.
    market_options = c.options.get("fetchMarkets")
    if isinstance(market_options, dict) and isinstance(market_options.get("types"), list):
        market_options["types"] = ["spot"]
    if venue == "okx":
        c.timeframes["1d"] = "1Dutc"
    if venue == "mexc":
        c.set_markets(c.fetch_spot_markets())
    return c


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("shortlist", "production", "history-dir", "registry", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--closed-day", type=date.fromisoformat, required=True)
    args = parser.parse_args()

    rows = audit(read_csv(args.shortlist), read_csv(args.production), args.closed_day,
                 args.history_dir, json.loads(args.registry.read_text()),
                 get_coingecko, spot_client)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows, indent=2, allow_nan=False) + "\n")
    temporary.replace(args.output)


if __name__ == "__main__":
    main()
