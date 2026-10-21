"""Observational fundamentals overlay. Never changes radar scores or ordering."""
import argparse
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

VERSION = 1


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def ratio(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def normalized(value):
    return str(value or '').strip().casefold()


def unique_match(rows, **fields):
    matches = [r for r in rows if all(normalized(r.get(k)) == normalized(v)
                                     for k, v in fields.items())]
    return matches[0] if len(matches) == 1 else None


class Source:
    """24h cache, bounded requests, no stale fallback, and redacted error messages."""
    def __init__(self, cache, now=None, budget=65):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.now = now or datetime.now(timezone.utc)
        self.budget = budget
        self.calls = 0
        self.errors = []
        self.last_call = 0
        self.started = time.monotonic()

    def get(self, url, params=None, headers=None):
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        path = self.cache / (key + '.json')
        try:
            stored = json.loads(path.read_text())
            age = self.now.timestamp() - stored['fetched_at']
            if 0 <= age < 86400:
                return stored
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if self.calls >= self.budget or time.monotonic() - self.started > 450:
            self.errors.append('request_budget_exhausted')
            return None
        # Conservative pacing for both public APIs. No unbounded retries.
        time.sleep(max(0, 6.1 - (time.monotonic() - self.last_call)))
        self.calls += 1
        self.last_call = time.monotonic()
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            result = {'fetched_at': datetime.now(timezone.utc).timestamp(),
                      'url': url, 'params': params, 'data': response.json()}
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(result, allow_nan=False))
            tmp.replace(path)
            return result
        except (requests.RequestException, ValueError, OSError) as exc:
            # Exception text may contain credentials; keep only the class name.
            self.errors.append(f'{url}: {type(exc).__name__}')
            return None


def window_metrics(payload, now):
    """Require every UTC calendar day; exclude today's incomplete bucket."""
    end = int(now.timestamp()) // 86400 * 86400
    values = {}
    for item in (payload or {}).get('totalDataChart', []):
        try:
            timestamp, raw = item
            day = int(timestamp) // 86400 * 86400
            value = number(raw)
            if value is not None:
                values[day] = value
        except (TypeError, ValueError):
            continue

    def total(days, offset=0):
        dates = [end - 86400 * i for i in range(offset + 1, offset + days + 1)]
        return sum(values[d] for d in dates) if all(d in values for d in dates) else None

    current, previous = total(30), total(30, 30)
    growth = ratio(current, previous)
    return {'30d': current, 'previous_30d': previous,
            'growth_30d': growth - 1 if growth is not None else None,
            '365d': total(365),
            'last_complete_day': datetime.fromtimestamp(max((d for d in values if d < end), default=0), timezone.utc).date().isoformat()
            if any(d < end for d in values) else None}


def trend(fees, revenue):
    if fees is None or revenue is None:
        return 'INSUFFICIENT DATA'
    if fees > .1 and revenue > .1:
        return 'IMPROVING'
    if fees < -.1 and revenue < -.1:
        return 'DETERIORATING'
    return 'MIXED'


def assess(row, coins, markets, protocols, source):
    out = {'fundamentals_version': VERSION,
           'fundamentals_observed_at': source.now.isoformat(),
           'fundamentals_status': 'INSUFFICIENT DATA',
           'fundamentals_confidence': 'INSUFFICIENT',
           'fundamentals_mapping': 'unresolved',
           'fundamentals_unlock_risk': 'UNKNOWN — unlock feed not integrated'}
    coin = unique_match(coins, symbol=row.get('symbol'), name=row.get('name'))
    if coin is None:
        out['fundamentals_note'] = 'No unique exact name+symbol CoinGecko match'
        return out
    cg_id = coin['id']
    out['fundamentals_coingecko_id'] = cg_id
    out['fundamentals_mapping'] = 'exact_name_and_symbol'
    market = markets.get(cg_id, {})
    # Market payload timestamps, rather than cache age alone, determine freshness.
    try:
        age = (source.now - datetime.fromisoformat(market['last_updated'].replace('Z', '+00:00'))).total_seconds()
        fresh = 0 <= age <= 86400
    except (KeyError, TypeError, ValueError):
        fresh = False
    cap = number(market.get('market_cap')) if fresh else None
    fdv = number(market.get('fully_diluted_valuation')) if fresh else None
    circulating = number(market.get('circulating_supply')) if fresh else None
    total = number(market.get('total_supply')) if fresh else None
    out.update({'fundamentals_market_updated_at': market.get('last_updated'),
                'fundamentals_market_cap': cap, 'fundamentals_fdv': fdv,
                'fundamentals_fdv_to_market_cap': ratio(fdv, cap),
                'fundamentals_circulating_to_total': ratio(circulating, total)})
    protocol = unique_match(protocols, gecko_id=cg_id)
    if protocol is None or not protocol.get('slug'):
        out['fundamentals_confidence'] = 'LIMITED' if cap else 'INSUFFICIENT'
        out['fundamentals_note'] = 'No unique DefiLlama protocol mapping; economic data unknown'
        return out
    parent = protocol.get('parentProtocol')
    slug = parent.removeprefix('parent#') if isinstance(parent, str) and parent.startswith('parent#') else protocol['slug']
    out.update({'fundamentals_defillama_slug': slug,
                'fundamentals_sector': protocol.get('category'),
                'fundamentals_tvl_usd': None if parent else number(protocol.get('tvl'))})
    complete = 0
    provenance = []
    for label, kind in [('fees', 'dailyFees'), ('revenue', 'dailyRevenue'),
                        ('holder_revenue', 'dailyHoldersRevenue')]:
        record = source.get('https://api.llama.fi/summary/fees/' + quote(slug, safe=''),
                            params={'dataType': kind, 'excludeTotalDataChart': 'false',
                                    'excludeTotalDataChartBreakdown': 'true'})
        payload = record['data'] if record and isinstance(record['data'], dict) else {}
        # Reject an explicitly different data type rather than count fees as revenue.
        if payload.get('dataType', kind) != kind or payload.get('gecko_id') != cg_id:
            payload = {}
        metrics = window_metrics(payload, source.now)
        for key, value in metrics.items():
            out[f'fundamentals_{label}_{key}'] = value
        if metrics['growth_30d'] is not None:
            complete += 1
        if record:
            provenance.append({'url': record['url'], 'dataType': kind,
                               'fetched_at': record['fetched_at']})
    out['fundamentals_sources'] = json.dumps(provenance, separators=(',', ':'))
    out['fundamentals_status'] = trend(out.get('fundamentals_fees_growth_30d'),
                                      out.get('fundamentals_revenue_growth_30d'))
    out['fundamentals_confidence'] = 'MODERATE' if complete == 3 and cap else 'LIMITED'
    out['fundamentals_market_cap_to_holder_revenue_365d'] = ratio(
        cap, out.get('fundamentals_holder_revenue_365d'))
    out['fundamentals_holder_capture_30d'] = ratio(
        out.get('fundamentals_holder_revenue_30d'), out.get('fundamentals_revenue_30d'))
    out['fundamentals_note'] = 'Observational; TVL is not tokenholder equity; supply ratios are not unlock forecasts'
    return out


def enrich(radar, source):
    cg_base = 'https://api.coingecko.com/api/v3'
    key = os.environ.get('COINGECKO_DEMO_API_KEY')
    headers = {'x-cg-demo-api-key': key} if key else {}
    coin_record = source.get(cg_base + '/coins/list', headers=headers)
    protocol_record = source.get('https://api.llama.fi/protocols')
    coins = coin_record['data'] if coin_record and isinstance(coin_record['data'], list) else []
    protocols = protocol_record['data'] if protocol_record and isinstance(protocol_record['data'], list) else []
    ids = []
    for row in radar.to_dict('records'):
        match = unique_match(coins, symbol=row.get('symbol'), name=row.get('name'))
        if match:
            ids.append(match['id'])
    markets = {}
    for start in range(0, len(ids), 250):
        record = source.get(cg_base + '/coins/markets',
                            params={'vs_currency': 'usd', 'ids': ','.join(sorted(set(ids[start:start+250]))),
                                    'per_page': 250, 'page': 1}, headers=headers)
        if record and isinstance(record['data'], list):
            markets.update({r['id']: r for r in record['data'] if 'id' in r})
    rows = []
    for row in radar.to_dict('records'):
        try:
            extra = assess(row, coins, markets, protocols, source)
        except (TypeError, ValueError, KeyError) as exc:
            extra = {'fundamentals_status': 'INSUFFICIENT DATA',
                     'fundamentals_confidence': 'INSUFFICIENT',
                     'fundamentals_observed_at': source.now.isoformat(),
                     'fundamentals_note': 'Provider schema error: ' + type(exc).__name__}
        rows.append({**row, **extra})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports-dir', default='reports')
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()
    reports, data = Path(args.reports_dir), Path(args.data_dir)
    radar = pd.read_json(reports / 'breakout_radar.json')
    # Strip a previous overlay if this is an on-demand rerun.
    radar = radar[[c for c in radar if not c.startswith('fundamentals_')]]
    source = Source(data / 'fundamentals_cache')
    enriched = enrich(radar, source)
    report_time = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    snapshots = data / 'fundamentals_snapshots'
    snapshots.mkdir(parents=True, exist_ok=True)
    snapshot = {'schema_version': VERSION, 'observed_at': source.now.isoformat(),
                'completed_at': datetime.now(timezone.utc).isoformat(),
                'requests': source.calls, 'errors': source.errors,
                'catalog_sources': ['https://api.coingecko.com/api/v3/coins/list',
                                    'https://api.llama.fi/protocols'],
                'records': json.loads(enriched.to_json(orient='records', date_format='iso'))}
    (snapshots / (report_time + '.json')).write_text(json.dumps(snapshot, indent=2, allow_nan=False))
    enriched.to_csv(reports / 'breakout_radar.csv', index=False)
    enriched.to_json(reports / 'breakout_radar.json', orient='records', date_format='iso')
    cols = ['symbol', 'fundamentals_status', 'fundamentals_confidence', 'fundamentals_note']
    print(enriched[[c for c in cols if c in enriched]].to_string(index=False))
    print(f'Fundamentals requests: {source.calls}; provider errors: {len(source.errors)}')


if __name__ == '__main__':
    main()
