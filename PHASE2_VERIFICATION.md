# Phase 2 verification gates (report-only)

The sector surveillance has two layers:
- Legacy **symbol-based baskets** remain available for research and are explicitly **unverified**. They must not trigger notifications.
- **Vetted-ID baskets** are configured in `config/sector_coin_ids.json`. The registry is intentionally empty until each LunarCrush coin ID and sector classification is independently verified. Never populate it merely by symbol matching. An empty basket reports insufficient baseline/coverage rather than a spurious volume alert. ID snapshot history is stored at `data/volume_snapshot_history_by_id.json` separately from legacy symbol snapshots; both use dated snapshots.

For each analyzed coin, production reports `technical_status`, `technical_reasons`, and daily EMA50, EMA100, EMA200 values when valid. Technical confirmation requires **300 consecutive completed daily UTC price bars** ending yesterday, EMA50 > EMA100 > EMA200, positive five-day EMA50 slope, and price between 97% and 110% of EMA50. A gap, short history, or current-day candle does not count. Current scanner history is usually only ~90 days, so expect **INSUFFICIENT EMA HISTORY** unless previously backfilled data are available in `data/history_<id>.csv`. This deliberately does not claim a confirmed signal where technical evidence is unavailable. No changes are made to the original breakout score or existing stage.

`notification_readiness` flags are included in `reports/volume_surge_latest.json`. **Push eligibility remains false by design**, even for a 2x or 3x volume surge: sector-ID membership, source definition, independent technical verification, deduplication, and delivery have not all been validated. No automated alerts are enabled by this change.

Review gates before enabling delivery: curate ID-based sector registry; check that LunarCrush volume represents the intended spot-market scope; accumulate seven comparable daily ID snapshots; verify price-history backfill coverage; validate positive and negative cases against live published reports; design and test duplicate suppression.
