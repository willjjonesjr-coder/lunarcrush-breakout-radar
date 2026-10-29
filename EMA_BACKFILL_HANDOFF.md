# EMA backfill-to-production handoff

Production currently calculates EMA confirmation using `data/history_<LunarCrush ID>.csv` (typically only 90 days). The historical smoke workflow's CCXT backfiller writes 500-bar OHLCV data to `data_price/<ID>.csv`, but its outputs are **workflow artifacts** and are not automatically checked into the production repo.

This change lets Phase 2's technical confirmation select `data_price/<ID>.csv` only when **all** of the following are true:
1. `config/symbol_map.json` contains the exact asset ID mapped explicitly to an exchange/pair.
2. `reports/backfill_inventory.csv` contains exactly one matching `ok` or `partial` row with the same ID, exchange, pair, and no reported gaps.
3. The price CSV exists, and its recorded exchange/pair match the mapping.
4. Technical confirmation independently verifies 300 consecutive completed UTC daily bars through yesterday.

Otherwise it falls back to LunarCrush history and emits insufficient-history reasons as appropriate. Raw breakout scores and stages are unchanged. No unverified ticker guesses can qualify. Coverage statistics are published at `reports/ema_coverage_latest.json`, and each asset's `ema_history_source` identifies its input.

## To actually backfill and deploy price files
From GitHub Actions, manually dispatch **Historical Signals Smoke Test** on a branch with the backfill workflow, first with `top=20`, then `top=80` if results and identity mapping check out. Download the `historical-smoke-results` artifact and inspect `reports/backfill_inventory.csv`, `data_price/`, and `logs/backfill.log`. Verify each intended asset ID and exchange contract. Do not treat a guessed ticker pair as vetted.

Only verified ID-to-exchange/pair mappings and corresponding reviewed price files plus inventory should be introduced into production. The smoke workflow itself does **not** publish these files to `main`; until they are available in the production checkout, EMA coverage will remain limited. A safe upload/persistence strategy (PR-reviewed files or a verified artifact download) is a separate required deployment step.

This connection does not trigger a smoke workflow or market order and does not grant new API scopes.
