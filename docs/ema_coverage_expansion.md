# Missing EMA coverage expansion — research only

The November 23 unified EMA coverage audit (run `45109654773`) classified
300 candidates: 43 production EMA evaluable, 41 eligible for provisional
research, 4 conflicted, **100 unclassified missing EMA**, and **112 without
matching research artifacts**. The last two categories comprise the target
discovery pool of up to 212 candidates in that specific snapshot. They are
not all confirmed identity failures and their membership changes over time.

## Run

After merging, dispatch **Expand missing EMA research coverage (no alerts)**
on main with:
- `coverage_run_id=45109654773` (or a newer verified unified coverage run)
- `batch_count=40` to start, then 60 after examining errors and API load
- `exchanges=kraken,coinbase,binance,okx,bybit,bitget,gate,mexc,kucoin`

The workflow validates the source run, fetches the exact production
`reports/breakout_radar.csv` from that commit, and joins by LunarCrush
coin ID plus exact name and symbol. It selects only
`NO_MATCHING_RESEARCH_ARTIFACT` and `UNCLASSIFIED_MISSING_EMA` with
missing production EMA values. It **does not include** the earlier 41
research-ready assets, four conflicting assets, or already evaluable assets.

Within these unresolved categories, rank by existing breakout score.
Low market capitalization or liquidity is **not** an exclusion: caution
fields travel with the queue. The initial run samples 40 candidates with
one exact spot USD/USDT/USDC pair per exchange to bound CCXT requests.

The workflow reuses the existing nine-exchange research audit to check
continuous, completed UTC price histories for **at least 300 daily bars**
and writes an exchange-discovery CSV and JSON. OHLCV gaps, stale series,
unavailable markets, unsupported pairs, and provider errors remain
visible; missing values are never filled in synthetically.

## Interpretation and next action

Outputs are in the `expanded-ema-coverage-research` artifact:
`all_targets.csv`, `selected_batch.csv`, `research_queue.json`,
`exchange_discovery.csv`, `exchange_discovery.json`, and source-run
provenance. A 300-bar-ready exchange pairing is only a **candidate for
cross-source price corroboration and provisional EMA research**, not a
verified coin mapping. Review duplicates, name conflicts, contract
conflicts, exact date-aligned independent prices, liquidity, and history
quality before computing research EMAs.

Subsequent batches should use a new queue offset or a refreshed audited
cohort; rerunning the same initial 40 does **not** expand unique coverage.
A future follow-up can introduce an explicit offset/pagination for
batch 2 and batch 3 after the first audit.

No production scores, ranking, verified coin inventory, symbol maps,
`data_price/` files, or breakout alerts are modified. This step is for
discovery and coverage diagnosis only.
