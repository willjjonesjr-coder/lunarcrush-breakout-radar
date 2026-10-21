# Observational fundamentals overlay

Run `python fundamentals.py` after `python scanner.py`. The production workflow runs this step before archiving and committing the radar. Existing scores, stages, ordering and scheduling are preserved. Provider failures do not stop the scan; unexpected overlay failures are visible as workflow warnings.

Sources: [CoinGecko](https://docs.coingecko.com/demo/reference/coins-markets) and [DefiLlama](https://api-docs.defillama.com/llms-free.txt). Attribution: market/supply data from CoinGecko; protocol financial data from DefiLlama. Optional repository secret `COINGECKO_DEMO_API_KEY` enables Demo authentication; without it public access is attempted and may be limited or refused. No paid subscriptions are required by this code. Check provider terms before redistributing data commercially.

## Outputs

The CSV/JSON radar gains `fundamentals_` columns. `data/fundamentals_snapshots/<UTC timestamp>.json` retains each observation, source fetch times, errors and schema version. `data/fundamentals_cache/` retains raw responses for 24 hours. These directories are included in the existing `git add data reports` workflow. Cache filenames never contain credentials.

- Exact name AND symbol must identify one CoinGecko asset. No ticker-only guesses. Renames and ambiguous identities remain unresolved.
- One DefiLlama protocol must map to that CoinGecko ID. Where the unique mapped entry references an explicit parent, its parent summary is used and its child TVL is omitted. Every financial response must confirm the same CoinGecko ID. Multiple protocol versions are deliberately not summed; they can overlap. Chains and unsupported projects remain unknown until reviewed mappings are introduced.
- Fees, protocol revenue and holder revenue are fetched separately. Missing observations are never converted to zero. A 30-day total requires all preceding 30 complete UTC days; growth requires all 60 days. Today's partial bucket is excluded. A zero prior baseline has undefined growth.
- Economic trend is IMPROVING when both fees and revenue grow more than 10%; DETERIORATING when both fall more than 10%; otherwise MIXED. Missing either growth metric means INSUFFICIENT DATA. These are provisional descriptive thresholds, not validated trading rules or a fair-value model.
- Confidence is MODERATE only when all three economic growth series and a fresh market cap are available; otherwise LIMITED or INSUFFICIENT. This measures coverage, not investment quality or audited financial reliability.
- Market cap / holder revenue uses **365 complete days**, never annualized single-day or 30-day revenue. A zero denominator produces unknown, not an infinite or artificially attractive ratio. It is not a P/E ratio or a shareholder claim.
- FDV/market cap and circulating/total supply are descriptive supply ratios. They do not predict unlock dates, future prices or issuance. Unlock risk explicitly remains UNKNOWN. Unlock feeds, net flows, active users, incentive adjustments and sector-relative valuation ranks are not yet integrated.
- TVL is context only; it is neither tokenholder equity nor a valuation score. Provider metric definitions and attribution mechanisms still need project-specific review.

At most 65 external requests per invocation, with 6.1-second spacing, a 10-second network timeout and no retries. Normal cost is two catalogs, one batched CoinGecko market request per 250 mapped assets, plus three calls per uniquely mapped protocol. Cache hits do not use requests. Budget exhaustion produces unknown fields. Requests are independent of LunarCrush quotas. New requests stop after 450 seconds; the workflow caps the step at ten minutes.

## Validation and backtesting

Run `python -m unittest discover -s tests -p 'test_fundamentals.py' -v`.

Snapshots start accumulating only when the overlay actually runs. Historical charts fetched today are revised data available today, not evidence those values were known in the past. A future backtest must join snapshots by their completed/available timestamp at or before the signal time and must never join today's fundamentals backward. No changes to ranking or the existing backtest are made until prospective observations establish incremental usefulness.
