# Production market regime integration

The nightly production workflow now calls `production_regime.py` after the scanner/fundamentals overlay and before generating the sortable report. It reuses `market_regime.regime` rather than introducing another model. Regime is market context only: candidate scores, rankings and eligibility remain unchanged.

## Independent data inputs

`config/production_regime.json` defines 20 explicit Kraken spot USD pairs including BTC, ETH and 18 established altcoins. This fixed, equal-participation basket is independent of the scanner's finalists and its current market-cap limits. It is a liquid-market proxy, not the entire crypto market or a market-cap-weighted index. Pair/base/quote/spot metadata is checked against the configured market. No LunarCrush-to-exchange ticker guesses or provisional research mappings are used. Provider: public Kraken market data via CCXT, no exchange credentials.

A maximum of 500 completed UTC daily bars per asset is retained in `data/market_regime_prices`. Each asset must have at least 230 **consecutive** valid days ending on the latest completed day. Missing dates, nonpositive prices and invalid volumes break continuity; only the valid suffix after the last gap is eligible. Today's unfinished bucket is excluded. Same-day complete caches are reused. Requests have a 10-second exchange timeout and a five-minute refresh budget, with an eight-minute workflow step limit. Public exchange requests do not consume LunarCrush quota.

BTC and ETH are mandatory. At least 12 assets and 70% of the configured basket must be available: with the current 20-asset basket this means at least 14 assets. The original model's breadth includes BTC and ETH as well as eligible altcoins. Fixed membership and one-exchange coverage are limitations; historical results also reflect today's chosen basket, not historical point-in-time membership.

## Existing model

The model retains trend (30%), breadth (25%), momentum (20%), participation (15%) and optional sentiment (10%). No sentiment feed is supplied in this integration, so the four observable component weights are proportionally renormalized. Sentiment is marked unavailable, not assumed neutral. Existing EMA50/100/200 logic, three-observation smoothing, direction classifications, strength and seven-observation changes remain unchanged. The adapter supplies contiguous daily data, so those observation periods are calendar-day periods for current production readings.

The output is a descriptive 1–100 bearish-to-bullish regime score, not a return forecast. The fixed basket and thresholds have not been validated as a trading filter. The strength metric remains the existing model's distance-from-neutral measure, not ADX.

## Outputs and failure behavior

- `reports/market_regime_latest.json`: current score, classification, date, component scores, coverage and availability.
- `reports/market_regime.csv`: daily regime history for the current available basket.
- `reports/market_regime_inventory.csv`: per-pair freshness, usable bars and failure reasons.
- Radar, full candidates and separated assets: attached `market_regime_` context fields.
- Sortable HTML: a market-regime banner and selectable regime fields.
- Actions summary, archived daily reports and artifact: regime reading and diagnostics.

Unavailable or stale inputs cause a new UNAVAILABLE summary with null score and an explicit reason. Previous reports and candidate context are overwritten so stale bullish/bearish context is not presented as current. Expected provider outages do not stop the radar. Unexpected code or filesystem failures remain visible workflow failures. The adapter never silently publishes a BTC-only reading as broad market breadth.

The historical/provisional workflows remain available for research and are not the production input source. Production scheduling stays at 9 PM America/New_York.

The Production market regime tests workflow executes a live-data validation job on pull requests and manual dispatch, separately from the full production scan. It checks for an AVAILABLE reading and uploads its coverage/inventory without committing radar outputs.
