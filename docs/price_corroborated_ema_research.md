# Price-corroborated EMA research pathway

This is a **research-only** alternative to requiring contract-level identity documentation for the 24 incremental CEX candidates discovered by the expanded exchange coverage audit.

1. Dispatch the `Price corroborate incremental CEX EMA research` workflow with the run ID of the completed expanded-CEX audit. It rebuilds the 24-candidate readiness set from that artifact; the source list is not hard-coded.
2. For each candidate, fetch recent *completed* 500 daily UTC candles using CCXT for exact spot markets on added CEXs. Use archived LunarCrush `data/history_<coin_id>.csv` daily `close` observations as an **independent** market-price reference. Historical CoinGecko reference fetch is not currently implemented; missing LunarCrush prices fail closed, never replaced by guessed data.
3. Match daily closes by **exact UTC date**, requiring at least three *consecutive* matching dates ending on the latest completed UTC day (five checked where available). Every day's absolute difference must be <=2% of the LunarCrush reference. Do not interpolate, shift by a day, or use moving 24-hour snapshots as if they were timestamp-aligned historical candles without the relevant caveat.
4. Reject/flag explicit identity contradictions, price deviations beyond 2%, missing/latest-day histories, invalid candles, flat/stale series, and unrecognized asset pairs. USDT/USDC are treated as USD-like for a **provisional** comparison, with a visible quote-parity caveat.
5. A `PRICE_CORROBORATED` result saves price candles to `reports/price_corroboration_research/provisional_ema/<coin_id>.csv` and computes independent `PROVISIONAL EMA` technical status. No assets are added to `data_price`, `config/symbol_map.json`, verified inventory, production rankings, or alerts.
6. Review `price_corroboration.csv` for full aligned day/reference/exchange price and percentage-difference arrays, EMA outputs, failures and warnings. `price_corroboration.json` reports counts; **fully_verified, production_approvals, alerts remain zero**.

The 2% tolerance is an initial research policy and not a validated identity-proof threshold. Source-specific pricing conventions and wrapped/native token differences can create false matches; any known conflicting token or contract must be entered in `config/price_corroboration_conflicts.json`, which blocks research promotion.

The workflow runs automatically **tests only** on PRs; price research must be manually dispatched after merging. The original production identity gate is unchanged.
