# Refresh the current provisional EMA research cohort

This **manual, research-only** workflow refreshes historical EMA50/100/200
values for the 41 candidates in the successful provisional ranking run
`45280254375`. In that run **32** were still in the current 300-coin
production selection, and **9** were outside it. The exact refresh target
may differ later because the selection rolls daily.

It reads the historical ranking CSV and the original provisional identity
report from run `41746836284`. Each candidate's LunarCrush coin ID,
name and symbol must agree with the originally researched evidence.
An exchange/pair is reused **only** when the original source has
`PROVISIONAL READY` and names an exact, active spot pair from
Kraken, Coinbase or Binance. No ticker guesses, alternative pairs,
identity approvals or live alert promotions are made.

For currently selected candidates with a matching original source, fetch
at least 300 contiguous completed UTC daily OHLCV bars and compute
provisional EMA50/100/200 through yesterday using the existing algorithm.
A source failure is recorded per candidate and never creates a price
or EMA by interpolation or by carrying forward historical values.

Candidates outside today's selected cohort remain in the output with
`RETAINED_HISTORICAL_ONLY` and are not refetched. A candidate's
selection or identity changing since the archived ranking requires
explicit review rather than silent adoption.

## Run and output

1. After PR validation and merge, open **Refresh current provisional EMA
   research (no alerts)** and select the `main` branch.
2. Keep `ranking_run_id=45280254375` and
   `provisional_run_id=41746836284`, or replace them with comparable
   successful research runs with unexpired artifacts.
3. Download the `refreshed-provisional-ema-research` artifact containing
   `refreshed_ranking.csv` and `summary.json`.

The output reports identity warnings, prior and current technical statuses,
exchange provenance, refreshed bars, latest completed UTC day, and reasons
for failed or withheld updates. Statuses are research-only; all rows have
`production_eligible=NO` and `alert_eligible=NO`.

**Important:** Refreshing an originally corroborated spot pair is not
independent current-day price corroboration or a new canonical
identity check. A refreshed `PROVISIONAL EMA ALIGNED` outcome is a
research finding, **not a confirmed breakout alert**. Historical
LunarCrush social and sentiment scores in the ranking are not refreshed
by this workflow. The output must not be used to represent current
multi-signal breakout confirmation without fresh independent evidence.

The job does not modify `config/symbol_map.json`, `data_price/`, the
production radar, production EMA inventory, ranking, or notifications.
