# Provisional EMA candidate research ranking

This is a separate **research-only** ranking of candidates marked `research_ready=YES`
by the unified 300-coin EMA coverage audit. The Nov 23, 2026 audit run
`45109654773` identified **41** such historical candidates. These are not
automatically verified identities, confirmed breakouts, or live alerts.

## Execution

Dispatch **Provisional EMA research ranking (no alerts)** after merging its PR.
The workflow defaults to the successful coverage run `45109654773`, 47-CEX
price research run `44292165792`, and provisional EMA run `41746836284`.
The runs must still have unexpired compatible artifacts.

The workflow creates `reports/provisional_ema_research_ranking/ranking.csv`
and `summary.json` as a downloadable artifact. It neither commits any data
nor updates production files. The CSV is sorted by the existing observed
breakout score; it does not change or recalculate that score. Smaller or
lower-liquidity coins stay in the ranking with caution flags, not exclusions.

## Safety and freshness

- Candidate selection is constrained by the coverage audit's `research_ready`
  and `RESEARCH_TO_PRODUCTION_HANDOFF` labels. Production EMA fields must
  remain empty for these candidates.
- Independently supplied price and provisional research evidence is joined
  by LunarCrush coin ID and checked for name/symbol conflicts and duplicates.
- EMA values are shown only if the source provides all positive finite
  EMA50/100/200 values and a `PROVISIONAL EMA` technical status.
- The freshness column is **FRESH** only when the source's completed
  UTC day matches the production report's completed UTC day. For a provisional
  report, global `as_of` must be the following UTC day. Unknown dates and
  archived values are marked `STALE_OR_UNVERIFIED`, not current signals.
- Historical research-ready classifications do not imply current-day technical
  confirmation. The manual workflow **does not** refresh market data.
- Every row is explicitly `PROVISIONAL / RESEARCH ONLY`, `production_eligible=NO`,
  and `alert_eligible=NO`. Unresolved canonical identities remain subject
  to user review.

This workflow intentionally does not incorporate provisional EMA values into
the production radar. Updating production research presentation or enabling
new alert pathways requires a separate explicitly reviewed change.

Run local regression tests: `python -m unittest tests.test_provisional_ema_research_ranking -v`.
