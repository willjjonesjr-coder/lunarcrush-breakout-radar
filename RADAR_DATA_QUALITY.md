# Production radar data quality

The production scanner scores **completed UTC daily bars** as of the scan's start. The current unfinished bucket is saved for later use, but excluded from feature calculations. This changes comparisons with older reports that mixed completed and partial daily observations.

The latest 30 completed calendar days must contain finite, nonnegative posts, contributors, interactions, sentiment, social dominance, volume, Galaxy Score and spam, plus positive closing prices. Every scoring input and both penalty inputs must also be finite. A missing calendar day stays missing; rows are never compressed into a shorter lookback and stale prices are never forward-filled. Thirty-day price return is optional context and needs an additional day.

When refreshing stored history, timestamps are sorted deterministically. New non-null field values supersede old values; sparse updates on an existing timestamp preserve previously observed values. This merge is field-wise and can combine observations from different fetches, so stored history remains a revised dataset rather than point-in-time evidence. No additional API calls or new price providers were added.

Only complete candidates define score normalization and enter the ranked shortlist. Missing values never receive neutral component scores. Coins with unavailable history or insufficient inputs appear as **INSUFFICIENT DATA**, never WEAK. A fully scored low-ranking coin can still be WEAK. If no coins are complete, the ranked JSON is an empty array; the candidate and coverage reports explain why. No historical backtest implementation was changed; older backtest thresholds are not validated against this revised live pipeline.

## Asset separation

Known symbol-and-name pairs, explicit provider categories/tags, and explicit wrapped or tokenized-security names identify assets outside the speculative crypto ranking. Stablecoins, wrapped assets, commodity-backed assets and tokenized securities appear in `separated_assets.csv/json` after the same size/liquidity/snapshot filters. This is a conservative, incomplete rule set, not independently verified identity mapping for every token. A ticker alone never determines asset type except for existing user-configured symbol exclusions. Unmatched assets remain `unclassified_crypto` and eligible. Ambiguous new asset types require reviewed rules; the existing identity-audit registry remains untouched.

Separation happens before the historical funnel and score normalization, preserving API budget for eligible candidates. Separated assets do not receive breakout scores. Their snapshot data stays available for inspection.

## Reports

- `breakout_radar.csv/json`: up to the requested number of complete, eligible finalists; the fundamentals overlay continues to enrich this shortlist.
- `radar_candidates.csv/json`: all historical candidates, including failures, with data status, missing feature names, missing-day counts by field, expected complete day and latest available price day.
- `separated_assets.csv/json`: filtered assets separated by type and reason.
- `radar_coverage.json`: counts of attempted, scored, incomplete, separated and final candidates, plus missing-input counts.

The workflow archives and uploads these reports and publishes coverage in the Actions summary. Historical candidate count remains 60 and the default shortlist remains 15. Existing scheduling and LunarCrush quotas are unchanged. This change does not integrate unlock feeds or broaden fundamental analysis beyond the shortlist.

Run `python -m unittest discover -s tests -p 'test_radar_quality.py' -v` for regression coverage, including a simulated end-to-end scan without API access.
