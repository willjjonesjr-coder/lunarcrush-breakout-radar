# Undervaluation research overlay — provisional, report-only

This is an independent **research-priority score**, NOT intrinsic fair value, a buy recommendation, or evidence that a price decline is unjustified. It does not change the existing LunarCrush breakout score, alerts, classifications, production universe or API request budget.

Run `python undervaluation_radar.py` after `fundamentals.py` and `phase1_monitor.py`, before `sortable_report.py`. The production workflow produces:
- `reports/undervaluation_radar.json`, independent score and explicit unrated counts;
- supplemental valuation-score, research classification, peer counts, price-dislocation context and evidence cautions in `breakout_radar.csv` and `breakout_radar.json`;
- sortable report columns alongside the original breakout score.

## Conservative evidence gate

An asset is **UNRATED** unless it has all of: exact name+symbol CoinGecko identity, moderate economic-data coverage, fresh market-cap-to-365d-*tokenholder*-revenue ratio, nonzero tokenholder revenue, 30d fees/protocol revenue/tokenholder revenue growth, FDV-to-market-cap, 30d price history, and at least three similarly assessed assets in the **same DefiLlama sector**. Missing values are *not* replaced with zero. A large price decline alone only results in a `SELL-OFF WATCH (NOT VALUATION)` label.

Provisional score weights (0–100): sector-relative market-cap/tokenholder revenue multiple 25, economic resilience 30, 30d price dislocation 15, snapshot liquidity-volume proxy 10, FDV dilution proxy 10, EMA recovery 5, and daily volume acceleration 5. These are research heuristics, not backtested probabilities or a fair-value estimate. The model does not currently measure realized capitalization, actual buy-side order depth, verified unlock schedules, or audited tokenholder claims. Peer valuation ranks are only meaningful for sufficiently comparable tokenholder economics and token mechanics, which will require further manual validation.

**Important coverage limitation:** Current fundamentals enrichment assesses only the top production highlights, not every analyzed coin. As a result most or even all 300 analyzed coins may correctly be **UNRATED**. This is an intentional safeguard, not an error. Before enabling valuation notifications, evaluate sector peer comparability, expand reliable fundamental coverage within provider budgets, accumulate historical point-in-time snapshots and backtest against subsequent returns. Do not backfill today's fundamental knowledge into historical decision dates.

No new API requests, notifications, or scoring-based exclusions are introduced by this step.
