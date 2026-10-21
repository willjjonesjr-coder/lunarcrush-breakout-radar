"""Daily-bar completeness and conservative asset separation for the live radar."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

# Symbol AND name must match. Symbols alone are not unique asset identities.
KNOWN_ASSETS = {
    ('USDG', 'global dollar'): 'stablecoin',
    ('RLUSD', 'ripple usd'): 'stablecoin',
    ('USD1', 'world liberty financial usd'): 'stablecoin',
    ('USDT', 'tether'): 'stablecoin',
    ('USDT', 'tether usd₮'): 'stablecoin',
    ('USDC', 'usd coin'): 'stablecoin',
    ('USDC', 'usdc'): 'stablecoin',
    ('DAI', 'dai'): 'stablecoin',
    ('USDE', 'ethena usde'): 'stablecoin',
    ('USDS', 'usds'): 'stablecoin',
    ('FDUSD', 'first digital usd'): 'stablecoin',
    ('TUSD', 'trueusd'): 'stablecoin',
    ('USDD', 'usdd'): 'stablecoin',
    ('WBTC', 'wrapped bitcoin'): 'wrapped_asset',
    ('WETH', 'weth'): 'wrapped_asset',
    ('WETH', 'wrapped ether'): 'wrapped_asset',
    ('CBBTC', 'cbbtc'): 'wrapped_asset',
    ('CBBTC', 'coinbase wrapped btc'): 'wrapped_asset',
    ('XAUT', 'tether gold'): 'commodity_backed',
    ('PAXG', 'pax gold'): 'commodity_backed',
}
METADATA_TYPES = {
    'stablecoin': 'stablecoin', 'stablecoins': 'stablecoin',
    'wrapped-tokens': 'wrapped_asset', 'wrapped tokens': 'wrapped_asset',
    'tokenized-stock': 'tokenized_security', 'tokenized stocks': 'tokenized_security',
    'tokenized-equities': 'tokenized_security', 'tokenized securities': 'tokenized_security',
}
REQUIRED_FEATURES = (
    'social_accel', 'contributor_accel', 'engagement_accel', 'sentiment_change',
    'social_dominance_change', 'volume_accel', 'social_price_divergence',
    'galaxy_score_change', 'price_change_7d', 'spam_change', 'last_price',
)
BAR_FIELDS = ('posts_active', 'contributors_active', 'interactions', 'sentiment',
              'social_dominance', 'volume_24h', 'galaxy_score', 'close', 'spam')


def classify_asset(row):
    symbol, name = str(row.get('symbol', '')).upper(), str(row.get('name', '')).strip().casefold()
    known = KNOWN_ASSETS.get((symbol, name))
    if known:
        return known, 'known symbol+name pair'
    for field in ('categories', 'tags'):
        tags = row.get(field, [])
        if isinstance(tags, str):
            tags = [tags]
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and tag.casefold() in METADATA_TYPES:
                    return METADATA_TYPES[tag.casefold()], f'provider {field}: {tag}'
    if re.search(r'\btokenized (stock|equity|security|securities)\b|\bxstock\b', name):
        return 'tokenized_security', 'explicit tokenized-security name'
    if name.startswith('wrapped '):
        return 'wrapped_asset', 'explicit wrapped-asset name'
    return 'unclassified_crypto', 'no separation rule matched; identity not independently verified'


def annotate_assets(frame):
    out = frame.copy()
    labels = [classify_asset(row) for row in out.to_dict('records')]
    out['asset_type'] = [x[0] for x in labels]
    out['asset_type_reason'] = [x[1] for x in labels]
    out['ranking_eligible'] = out['asset_type'].eq('unclassified_crypto')
    return out


def merge_history(previous, fresh):
    # Stable source order: new non-null observations supersede old ones. A sparse
    # update must not erase known values on the same timestamp.
    combined = pd.concat([previous, fresh], ignore_index=True)
    combined['time'] = pd.to_datetime(combined['time'], utc=True, errors='coerce')
    combined = combined.dropna(subset=['time'])
    return combined.groupby('time', sort=True, as_index=False).last()


def daily_history(hist, as_of):
    cutoff = pd.Timestamp(as_of).tz_convert('UTC').normalize()
    if hist.empty:
        return hist.copy()
    h = merge_history(hist.iloc[:0], hist)
    h = h[(h.time < cutoff) & (h.time == h.time.dt.normalize())]
    if h.empty:
        return h
    # Reindexing exposes gaps instead of treating seven rows as seven days.
    dates = pd.date_range(min(h.time.min(), cutoff-pd.Timedelta(days=30)),
                          cutoff-pd.Timedelta(days=1), freq='D', tz='UTC')
    return h.set_index('time').reindex(dates).rename_axis('time').reset_index()


def coverage(h, as_of):
    end = pd.Timestamp(as_of).tz_convert('UTC').normalize()-pd.Timedelta(days=1)
    dates = pd.date_range(end-pd.Timedelta(days=29), end, freq='D', tz='UTC')
    values = h.set_index('time').reindex(dates) if not h.empty else pd.DataFrame(index=dates)
    missing = {}
    for col in BAR_FIELDS:
        s = pd.to_numeric(values[col], errors='coerce') if col in values else pd.Series(np.nan, index=dates)
        valid = np.isfinite(s) & (s >= 0)
        if col == 'close':
            valid &= s > 0
        count = int((~valid).sum())
        if count:
            missing[col] = count
    actual = h.dropna(subset=['close']) if 'close' in h else h.iloc[:0]
    return {'expected_complete_day': end.isoformat(),
            'latest_price_day': actual.time.max().isoformat() if not actual.empty else None,
            'history_missing_fields': json.dumps(missing, sort_keys=True),
            'history_complete_30d': not missing}


def write_coverage(report_dir, all_rows, finalists, separated, as_of):
    statuses = all_rows['data_status'].value_counts().to_dict()
    summary = {'as_of': pd.Timestamp(as_of).isoformat(),
               'history_candidates': len(all_rows), 'data_status_counts': {k:int(v) for k,v in statuses.items()},
               'scored_candidates': int(all_rows['breakout_score'].notna().sum()),
               'finalists': len(finalists), 'separated_assets': len(separated),
               'missing_feature_counts': {}, 'history_missing_field_counts': {}}
    for row in all_rows.to_dict('records'):
        for key in str(row.get('missing_features', '')).split(','):
            if key:
                summary['missing_feature_counts'][key] = summary['missing_feature_counts'].get(key, 0)+1
        for key in json.loads(row.get('history_missing_fields', '{}')):
            summary['history_missing_field_counts'][key] = summary['history_missing_field_counts'].get(key, 0)+1
    if 'daily_spike_flag' in all_rows:
        summary['daily_spike_counts'] = {k:int(v) for k,v in all_rows['daily_spike_flag'].value_counts().items()}
    Path(report_dir, 'radar_coverage.json').write_text(json.dumps(summary, indent=2))
    print('Radar coverage: ' + json.dumps(summary, sort_keys=True))
    return summary
