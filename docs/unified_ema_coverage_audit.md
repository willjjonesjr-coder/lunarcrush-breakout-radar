# Unified EMA coverage audit

This report inventories the **300 production-history-selected candidates** and explains
which candidates have evaluable production EMA50/100/200 histories. It **does not**
modify symbol maps, verified inventory, research or production EMA calculations,
production scoring, coin identification approvals, or notifications.

Run `python -m tools.unified_ema_coverage_audit` for the committed production
CSV baseline. This baseline shows `NO_MATCHING_RESEARCH_ARTIFACT` for unknowns,
**not** an identification failure. To provide evidence, supply:

- `--identity`: master EMA identity audit CSV
- `--price`: 47-CEX `provisional_ema_summary.csv` or `price_corroboration.csv`
- `--provisional`: `provisional_ema/report.json` or equivalent research CSV
- `--history`: incremental CEX readiness CSV

Alternatively dispatch **Unified EMA coverage audit (read-only)** with the
corresponding completed workflow run IDs. Downloaded artifacts are segregated by
run type and joined **only by LunarCrush coin ID**, with optional name/symbol
consistency checks. Duplicate IDs, conflicting names, or symbols fail closed.
A missing or stale report must not be interpreted as an identity failure;
repeat the source research before decisions based on current candles.

Output artifact: `reports/unified_ema_coverage/coverage.csv` and `summary.json`.
Every row preserves a production score, production EMA state, identity and
corroboration evidence (if available), primary/secondary blockers, research-ready
label, provenance, and next action. If source artifacts lack adequate evidence,
the row remains explicitly unknown.

Only genuine production EMA50/100/200 availability counts as production evaluable.
`RESEARCH_TO_PRODUCTION_HANDOFF` means provisional technical research exists
but does not authorize live production alert eligibility. A research-ready label
is **not canonical token verification** and still requires the user's own
due diligence and explicit controls before any production promotion.

Recommended workflow: first run on PR (baseline + regression tests), then
dispatch the audit against selected recent research workflow run IDs. Compare
the blocker counts and 300-row CSV before making any promotion-policy changes.
