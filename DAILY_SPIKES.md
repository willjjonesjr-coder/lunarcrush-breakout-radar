# Daily volume and engagement spikes

For each completed UTC day t, separately for daily `volume_24h` and `interactions`:

    prior_7d_average[t] = mean(value[t-7], ..., value[t-1])
    spike_multiple[t] = value[t] / prior_7d_average[t]
    daily_accel[t] = spike_multiple[t] - 1

The tested day is excluded from its own baseline. All seven preceding calendar days and the tested day must have finite, nonnegative values. Gaps are never compressed or forward-filled. Zero baselines produce a ZERO BASELINE status and undefined ratio, never infinity. Today's unfinished daily bucket and future timestamps are excluded. Ratios are stored as fractions: 2.0 means +200%, or 3 times baseline. Multiples are stored separately to prevent confusion.

## Live scoring

The original latest-seven-day average / preceding-23-day average comparisons remain available as `volume_accel` and `engagement_accel`. `daily_spikes.score_share` defaults to 0.5, splitting the existing family weights:

| Component | Weight |
|---|---:|
| Volume broader trend | 5% |
| Volume daily spike | 5% |
| Engagement broader trend | 7.5% |
| Engagement daily spike | 7.5% |

Other feature weights, penalty calculations and stage thresholds are unchanged. Daily components use the existing cross-sectional normalization, so scores express relative strength among complete candidates, not an absolute prediction. Both daily ratios are required for ranking. `score_share: 0` removes their influence while retaining calculations and reporting; they still must be available for eligibility. Configuration must specify a share between zero and one.

`daily_spikes.flag_multiple` defaults to 2.0 (at least twice baseline, equivalent to +100%). Each candidate receives VOLUME, ENGAGEMENT, VOLUME + ENGAGEMENT, NONE or INSUFFICIENT DATA. A flag is descriptive and does not bypass price-extension, spam, asset-type or completeness checks. The threshold is provisional and not backtest validated.

## Outputs

Latest daily values, their preceding seven-day averages, spike multiples, percentage-change fractions and validity statuses appear alongside the existing indicators in both the full candidate report and the ranked radar. `daily_spike_history.csv/json` records every completed day available in the fetched/merged histories for the historical candidate pool; the first seven days have no complete baseline. Candidate IDs and symbols identify each series. Reports are archived and uploaded with production artifacts, and coverage includes daily spike flag counts.

The scanner still uses its existing 60 historical candidates and default 15 finalists. It requires no additional API calls. Scheduling remains daily at 9 PM America/New_York; this change does not provide intraday detection. Historical charts remain revised source data, and no existing backtest implementation or historical performance claims are changed.

Tests: `python -m unittest discover -s tests -p 'test_daily_spikes.py' -v` and the existing radar quality tests.
