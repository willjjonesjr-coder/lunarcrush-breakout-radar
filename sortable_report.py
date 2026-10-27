"""Build a standalone sortable radar report from existing saved JSON reports."""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

LABELS = {
 'market_regime_score':'Market regime score', 'market_regime_classification':'Market regime',
 'market_regime_coverage':'Regime data coverage', 'market_regime_change_7d':'Regime score change: 7 days',
 'market_regime_status':'Regime availability',
 'market_cap_label':'Market-cap label', 'liquidity_label':'Volume label',
 'price_extension_label':'7-day extension label', 'history_selection':'History processing',
 'finalist_label':'Highlight label', 'symbol':'Coin', 'name':'Name', 'breakout_score':'Breakout score', 'stage':'Stage',
 'volume_daily_accel':'Volume: day vs prior 7 days',
 'engagement_daily_accel':'Engagement: day vs prior 7 days',
 'volume_spike_multiple':'Volume spike multiple', 'engagement_spike_multiple':'Engagement spike multiple',
 'volume_accel':'Volume: 7-day vs 23-day trend', 'engagement_accel':'Engagement: 7-day vs 23-day trend',
 'social_accel':'Posts trend', 'contributor_accel':'Contributor trend',
 'price_change_7d':'Price change: 7 days','price_change_30d':'Price change: 30 days',
 'fundamentals_status':'Fundamental trend', 'fundamentals_confidence':'Fundamental confidence',
 'fundamentals_fdv_to_market_cap':'FDV / market cap',
 'fundamentals_market_cap_to_holder_revenue_365d':'Market cap / annual holder revenue',
 'daily_spike_flag':'Daily spike flag','data_status':'Data status', 'asset_type':'Asset type',
 'volume_day_value':'Day volume ($)', 'engagement_day_value':'Day interactions',
 'volume_prior_7d_avg':'Prior 7-day average volume ($)',
 'engagement_prior_7d_avg':'Prior 7-day average interactions',
 'last_price':'Last price ($)', 'market_cap':'Market cap ($)',
 'volume_24h_snapshot':'Snapshot volume ($)',
 'confirmation_label':'Breakout confirmation',
 'confirmation_blockers':'Confirmation cautions',
 'liquidity_tier':'Liquidity tier (volume proxy)',
 'liquidity_adjusted_score':'Liquidity-adjusted score (volume proxy)',
 'liquidity_volume_factor':'Liquidity volume factor',
}
PERCENT = {'market_regime_coverage','volume_daily_accel','engagement_daily_accel','volume_accel','engagement_accel',
 'social_accel','contributor_accel','sentiment_change','social_dominance_change',
 'price_change_7d','price_change_30d','galaxy_score_change','spam_change','social_price_divergence',
 'fundamentals_fees_growth_30d','fundamentals_revenue_growth_30d',
 'fundamentals_holder_revenue_growth_30d','fundamentals_holder_capture_30d',
 'fundamentals_circulating_to_total'}
TEXT = {'market_cap_label','liquidity_label','price_extension_label','history_selection','finalist_label','market_regime_classification','market_regime_status','symbol','name','stage','fundamentals_status','fundamentals_confidence',
        'daily_spike_flag','data_status','asset_type','liquidity_tier','confirmation_label','confirmation_blockers'}
DEFAULT = ['symbol','name','breakout_score','confirmation_label','liquidity_adjusted_score','liquidity_tier','volume_daily_accel','engagement_daily_accel',
           'volume_accel','engagement_accel','price_change_7d','market_cap_label','liquidity_label','data_status','fundamentals_status']


def read_rows(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data,list):
        raise ValueError(f'{path.name} must contain an array')
    return data


def add_liquidity_proxy(row):
    """Add a descriptive, volume-only ranking; do not alter production breakout_score."""
    result = dict(row)
    volume = result.get('volume_24h_snapshot')
    score = result.get('breakout_score')
    if isinstance(volume, (int, float)) and math.isfinite(volume) and volume >= 0:
        if volume >= 50_000_000:
            tier, factor = 'HIGH (volume proxy)', 1.0
        elif volume >= 5_000_000:
            tier, factor = 'MODERATE (volume proxy)', 0.9
        else:
            tier, factor = 'LOW (volume proxy)', 0.75
        result['liquidity_tier'] = tier
        result['liquidity_volume_factor'] = factor
        if isinstance(score, (int, float)) and math.isfinite(score):
            result['liquidity_adjusted_score'] = round(score * factor, 6)
    else:
        result['liquidity_tier'] = 'UNKNOWN'
    return result


def payload(reports):
    finalists = read_rows(reports/'breakout_radar.json')
    candidates = read_rows(reports/'radar_candidates.json')
    lookup = {str(r.get('id')):r for r in finalists}
    # Only finalists actually have the separately fetched fundamental assessment.
    candidates = [{**r, **{k:v for k,v in lookup.get(str(r.get('id')),{}).items()
                            if k.startswith('fundamentals_')}} for r in candidates]
    groups = {('Analyzed candidates' if any('finalist_label' in r for r in finalists) else 'Finalists'):finalists}
    if (reports/'radar_candidates.json').exists():groups['All candidates']=candidates
    if (reports/'separated_assets.json').exists():groups['Separated assets']=read_rows(reports/'separated_assets.json')
    groups = {name: [add_liquidity_proxy(r) for r in group] for name, group in groups.items()}
    rows = [r for group in groups.values() for r in group]
    fields = dict.fromkeys(list(LABELS) + [k for r in rows for k,v in r.items()
                                          if type(v) in (int,float) and k not in ('id','fundamentals_version')])
    metrics = [{'key':k,'label':LABELS.get(k,k.replace('fundamentals_','Fundamental: ').replace('_',' ')),
                'kind':'text' if k in TEXT else 'number',
                'format':'percent' if k in PERCENT else 'number'} for k in fields]
    for r in rows:
        if r.get('breakout_score') is None and r.get('stage') == 'WEAK':
            r['stage']='INSUFFICIENT DATA'
    regime_path=reports/'market_regime_latest.json'
    market_regime=json.loads(regime_path.read_text()) if regime_path.exists() else None
    return {'market_regime':market_regime, 'generated_at':datetime.now(timezone.utc).isoformat(), 'groups':groups,
            'metrics':metrics, 'default_columns':DEFAULT,
            'observation_days':sorted({str(r['last_time']) for r in rows if r.get('last_time')})}


def build(reports, output):
    data=json.dumps(payload(Path(reports)),allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template=Path(__file__).with_name('sortable_report.html').read_text()
    comparator=Path(__file__).with_name('sort_rows.js').read_text()
    html=template.replace('/*__SORT_LOGIC__*/',comparator).replace('/*__REPORT_DATA__*/',data)
    Path(output).write_text(html)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports-dir',default='reports')
    parser.add_argument('--output',default='reports/radar_sortable.html')
    args=parser.parse_args()
    build(args.reports_dir,args.output)
    print('Sortable radar saved: '+args.output)


if __name__=='__main__':main()
