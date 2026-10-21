"""Each completed daily observation against its preceding seven calendar days."""
import numpy as np
import pandas as pd

from radar_quality import daily_history


def daily_comparisons(hist, as_of):
    h = daily_history(hist, as_of)
    out = h[['time']].copy() if 'time' in h else pd.DataFrame(columns=['time'])
    for label, field in [('volume', 'volume_24h'), ('engagement', 'interactions')]:
        raw = h[field] if field in h else pd.Series(np.nan, index=h.index, dtype=float)
        values = pd.to_numeric(raw, errors='coerce')
        values = values.where(np.isfinite(values) & (values >= 0))
        # Shift BEFORE rolling: the day being tested never dilutes its baseline.
        baseline = values.shift(1).rolling(7, min_periods=7).mean()
        valid = values.notna() & baseline.notna()
        multiple = (values / baseline.where(baseline > 0)).replace([np.inf, -np.inf], np.nan)
        out[f'{label}_day_value'] = values
        out[f'{label}_prior_7d_avg'] = baseline
        out[f'{label}_spike_multiple'] = multiple
        out[f'{label}_daily_accel'] = multiple - 1
        out[f'{label}_spike_status'] = np.select(
            [valid & baseline.gt(0), valid & baseline.eq(0)],
            ['VALID', 'ZERO BASELINE'], default='MISSING DATA')
    return out


def latest_spikes(hist, as_of):
    comparisons = daily_comparisons(hist, as_of)
    fields = [c for c in comparisons if c != 'time']
    if comparisons.empty:
        return {c: ('MISSING DATA' if c.endswith('_status') else np.nan) for c in fields}
    return comparisons.iloc[-1][fields].to_dict()


def classify_spike(row, threshold=2.0):
    volume = row.get('volume_spike_multiple', np.nan)
    engagement = row.get('engagement_spike_multiple', np.nan)
    v, e = pd.notna(volume) and volume >= threshold, pd.notna(engagement) and engagement >= threshold
    if v and e:
        return 'VOLUME + ENGAGEMENT'
    if v:
        return 'VOLUME'
    if e:
        return 'ENGAGEMENT'
    if pd.isna(volume) or pd.isna(engagement):
        return 'INSUFFICIENT DATA'
    return 'NONE'
