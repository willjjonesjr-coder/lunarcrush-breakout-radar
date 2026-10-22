# Reference checks are labels

Only asset-type separation and the configured explicit symbol exclusions remove assets from the main crypto universe. Market capitalization, snapshot trading volume and seven-day gains are descriptive reference checks. The existing values remain in config.json: $250M minimum and $10B maximum market cap, $10M daily volume and 35% seven-day gain. Missing values are UNKNOWN rather than automatic failures.

`market_cap_label`, `liquidity_label` and `price_extension_label` appear in the analyzed and full-candidate CSV/JSON and are selectable in the sortable view. These reference labels do not introduce score penalties or gate candidate selection. Existing extension/spam score penalties remain unchanged; snapshot ranking still determines processing priority.

The 300-history cap is an operational API/runtime budget, not an exclusion from discovery. `radar_candidates.csv/json` contains every non-excluded asset returned in the universe: analyzed assets have `history_selection=ANALYZED`; the rest have `OUTSIDE HISTORY BUDGET`, `data_status=NOT ANALYZED`, and null score. The main `breakout_radar.csv/json` now contains all analyzed rows, including unscored ones. Its top configured 15 scored rows receive TOP HIGHLIGHT rather than suppressing the remaining rows. These are the default Analyzed candidates view and optional All candidates view in the sortable HTML.

Missing daily history is labeled PARTIAL HISTORY when every required score input can still be computed; the existing rolling minimum-observation rules are retained, so these estimates may use fewer observations within their calendar windows and must be interpreted with that label. Truly missing score inputs remain INSUFFICIENT DATA with null score; no missing values are invented or assumed neutral. Such rows remain visible. Current/future daily bars remain excluded from calculations as a time-boundary rule.

Fundamentals enrichment remains limited to TOP HIGHLIGHT rows to preserve its independent request budget. Other analyzed rows show NOT ASSESSED. Market-regime context still attaches to all rows. No provider quotas or production schedule change. Because thousands of assets may appear in full discovery, API depth and the 300-history processing limit are explicitly reported rather than hidden.

Coverage reports distinguish visible universe size, histories analyzed, outside-budget assets, scored candidates, highlights, missing inputs and separated assets. Asset classification rules remain conservative and incomplete, as documented previously.

This policy supersedes earlier documentation describing size/volume/extension requirements and full 30-day completeness as eligibility filters, or describing the main radar as only 15 complete finalists.
