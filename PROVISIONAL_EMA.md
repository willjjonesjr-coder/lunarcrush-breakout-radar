# Provisional identity and EMA research

This opt-in research path implements a lighter matching standard without changing
verified histories, verified inventory, production scores, or alert eligibility.
It does not certify identity. User due diligence is still required.

Run `python provisional_ema.py`, then `python sortable_report.py`. Alternatively,
run **Provisional identity and EMA research** in Actions. That manual workflow
uploads a separate artifact, including a sortable view. It does not commit data,
change the scheduled production scan, import histories, merge, or deploy anything.

Inputs default to the full `data/universe_latest.csv` snapshot, the current
`reports/breakout_radar.csv` targets, and a freshly fetched CoinGecko catalog.
`--targets` can select another CSV with `id`, `name`, and `symbol` columns. The full
universe is still checked for collisions before targets are processed. There is
no new market-cap or liquidity exclusion, including for low-cap candidates.

## Evidence gates

- Match a unique name **and** symbol in both catalogs after Unicode NFKC, case,
  and whitespace normalization. Punctuation, ticker aliases, renames, wrapped
  tokens and migrations are not silently equated. Duplicate IDs or names/symbols
  are withheld for review, including duplicates outside the target list.
- Canonical-ID or shared-network contract conflicts are withheld. Missing
  contract/native-chain documentation is flagged, not a blocker.
- Recheck the CoinGecko asset's detail identity, then require its tickers endpoint
  to list the exact CoinGecko market identifier and base/quote pair. Only Kraken,
  Coinbase Exchange and Binance USD/USDT spot pairs are currently supported.
  Stale/anomalous listings are excluded. Lookups use at most five ticker pages;
  a listing absent from those pages is withheld, not inferred from its symbol.
- The exchange must independently offer that exact active spot pair. Histories
  need at least 300 consecutive completed UTC daily bars through yesterday,
  finite positive OHLC prices, valid envelopes, and nonnegative volume. Exact
  overlapping candles may be deduplicated; conflicting duplicates fail. Today's
  incomplete candle is ignored, future or misaligned timestamps fail.
- EMA50/100/200 uses the same 300-bar research formula as the existing technical
  view, but emits **PROVISIONAL EMA ALIGNED / NOT ALIGNED**, never verified
  confirmation. Current but insufficient/gapped histories emit no EMA values.

Outputs live exclusively in `reports/provisional_ema/`: one CSV per accepted
LunarCrush ID and `report.json` with identity status, evidence URL/date, review
flags, history provenance, errors and provisional EMA fields. A failed recheck
removes that target's earlier history. Only report-listed successful histories
are usable; leftover files for targets no longer selected are not an inventory.
The sortable view joins by ID **and** normalized name/symbol, exposes separate
provisional columns, and withholds EMA values from prior-day reports.

`config/symbol_map.json`, approval registries, `data_price/`, verified inventory,
`technical_status`, verified EMA values, scoring and notifications are untouched.
To promote an asset later, use the existing explicit reviewed identity process.

## Operation and limits

No new LunarCrush requests are made. Public CoinGecko/exchange API calls are
rate-limited; rate limits, unavailable exchanges, unsupported markets, missing
listings or insufficient bars are visible review/history failures, not guesses.
The default six-second CoinGecko delay and bounded retry policy can make a large
batch slow. The manual workflow has a three-hour timeout. No live provider run
or production activation is implied by unit tests or by opening a draft PR.

Tests: `python -m unittest discover -s tests -v` and
`node tests/test_sort_rows.js`. New tests use deterministic provider fixtures.
