# iPad/GitHub edition

See `IPAD_GITHUB_SETUP.md` for the recommended iPad setup.

# LunarCrush Light-plan Altcoin Breakout Scanner

This project is designed around LunarCrush API v4 and the Light/Individual constraints:

- 10 requests/minute
- 2,000 requests/day
- `/public/coins/list/v1` for the universe
- `/public/coins/{coin}/time-series/v2` for historical coin/social/market data
- no API key stored in source code
- local CSV/JSON storage so the scanner can build its own history over time

LunarCrush's current API documentation shows that `/coins/list/v1` is cached and can return up to 1,000 rows per page, while `/coins/{coin}/time-series/v2` returns hourly/daily data including contributors, interactions, posts, sentiment, spam, price, volume, social dominance, AltRank and Galaxy Score.

## Setup

1. Install Python 3.11+.
2. Install dependencies:

   `pip install -r requirements.txt`

3. Set your API key in the environment:

   Linux/macOS:
   `export LUNARCRUSH_API_KEY="YOUR_KEY"`

   Windows PowerShell:
   `$env:LUNARCRUSH_API_KEY="YOUR_KEY"`

4. Run a live scan:

   `python scanner.py`

The script will create:
- `data/universe_latest.csv`
- `data/history_<coin_id>.csv`
- `reports/breakout_radar.csv`
- `reports/breakout_radar.json`

## API budget

The default workflow is intentionally conservative.

Typical daily usage:
- universe pagination: ~6 requests for ~5,500 coins
- historical calls: ~60 requests for finalists
- optional deep dives: not enabled by default

At 10 requests/minute, the historical stage is throttled automatically.

## Signal philosophy

The scanner looks for:

1. accelerating social activity
2. broadening contributor participation
3. accelerating interactions
4. improving sentiment
5. increasing social dominance
6. increasing trading volume
7. social momentum that is ahead of price
8. reasonable market-cap/liquidity constraints

The output is a ranking, not an automatic trade signal.

## Backtesting

`backtest.py` works on saved historical CSV files.

It evaluates whether a signal at time T is followed by:
- +10% / +20% / +50% forward return
- max forward drawdown
- breakout frequency

Example:

`python backtest.py --horizon 14 --threshold 25`

The backtest is deliberately point-in-time: features use only data available at T, and forward returns use later observations.

## Important

## GitHub Actions Workflow Catalog

The repository includes multiple workflows. Two are production-facing (`LunarCrush Breakout Radar`, `Anti-pump Backtest Analysis`), while the others are mainly for historical/regime research and validation.

| Workflow | File | Trigger(s) | Branch Scope | Purpose | Main Outputs |
|---|---|---|---|---|---|
| LunarCrush Breakout Radar | `.github/workflows/lunarcrush-radar.yml` | `schedule` (daily), `workflow_dispatch` | default branch | Runs the main LunarCrush scanner and publishes ranked breakout radar files. | `reports/breakout_radar.csv`, `reports/breakout_radar.json`, `reports/archive/*`, artifact `lunarcrush-breakout-radar` |
| Anti-pump Backtest Analysis | `.github/workflows/backtest.yml` | `schedule` (weekly), `workflow_dispatch` with inputs (`thresholds`, `horizons`, `strategy`) | default branch | Runs configurable backtests on saved data and uploads/commits backtest result CSVs. | `reports/backtest*.csv`, artifact `anti-pump-backtest-results` |
| Historical Signals Smoke Test | `.github/workflows/historical-smoke.yml` | `push` (selected paths), `workflow_dispatch` (`top`) | `feat/historical-signals` | Fast sanity check for historical backfill and EMA eligibility diagnostics. | `reports/ema_eligibility_diagnostics.csv.gz`, `reports/backfill_inventory.csv`, `data_price/`, `logs/backfill.log` |
| BTC ETH Regime Data Validation | `.github/workflows/btc-eth-regime.yml` | `push` (selected paths), `workflow_dispatch` | `feat/historical-signals` | Validates BTC/ETH data pull and computes a BTC/ETH-only regime preview. | `data_price/btc.csv`, `data_price/eth.csv`, `reports/btc_eth_inventory.csv`, `reports/btc_eth_regime_preview.csv` |
| Provisional Crypto Market Breadth | `.github/workflows/market-breadth.yml` | `push` (selected paths), `workflow_dispatch` | `feat/historical-signals` | Builds provisional universe and computes broader market breadth regime preview. | `reports/market_breadth_provisional.csv`, inventories/logs, runtime symbol mapping |
| Market Regime Tests | `.github/workflows/market-regime-tests.yml` | `push` (selected paths), `workflow_dispatch` | `feat/historical-signals` | Runs unit tests for market regime logic. | test logs in Actions run |
| Experimental Regime Backtest | `.github/workflows/regime-backtest.yml` | `push` (selected paths), `workflow_dispatch` | `feat/historical-signals` | End-to-end experimental regime pipeline: backfill, universe build, regime series, signal joins, robustness checks. | multiple regime backtest CSVs, inventories, runtime mapping, artifact `regime-backtest-results` |

### Recommended execution order

For day-to-day production use:
1. **LunarCrush Breakout Radar**
2. **Anti-pump Backtest Analysis** (after a successful scan, when you want updated evaluation)

For historical/regime research (feature branch):
1. **Historical Signals Smoke Test**
2. **BTC ETH Regime Data Validation**
3. **Provisional Crypto Market Breadth**
4. **Market Regime Tests** (or run earlier during code changes)
5. **Experimental Regime Backtest**

### Notes

- Feature-branch workflows are currently scoped to `feat/historical-signals` and are intended for research/validation rather than daily production scanning.
- Some workflows upload artifacts only and do not commit outputs back to the repository.
- Production workflows that commit files require `contents: write`.

LunarCrush data can be revised, and cached universe data can lag the live market.

This backtest explores fixed thresholds rather than validating the live cross-sectional ranking. It uses currently selected coins and revised historical data, so selection and survivorship bias remain. Horizons count daily observations. Returns exclude fees and slippage; drawdown uses daily closes relative to entry. Signals overlap. On iPad run Actions → LunarCrush Backtest after a successful scan.
