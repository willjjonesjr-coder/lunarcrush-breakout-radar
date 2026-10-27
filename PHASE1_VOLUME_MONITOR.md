# Phase 1 — Market/sector volume surveillance and confirmation labels

## What runs
After the existing production scanner and fundamentals overlay, `python phase1_monitor.py` reads **only already-fetched** LunarCrush data: `data/universe_latest.csv` and `reports/breakout_radar.{csv,json}`. No extra LunarCrush API requests are made, and the raw breakout score, existing stage, finalists, scan budget, and production 50 scoring remain unchanged.

It writes:
- `data/volume_snapshot_history.json`: one 24h reported-volume snapshot per UTC date, keeping up to 40 days.
- `reports/volume_surge_latest.json`: tracked-universe, BTC, ETH and named sector-basket comparisons.
- `confirmation_label` and `confirmation_blockers` columns on the published breakout report, also visible and sortable in `radar_sortable.html`.

### Volume scope — interpret conservatively
**This is not an estimate of total global crypto-market spot trading volume.** Coin-list reported 24h volume may aggregate spot, derivatives or other provider sources; do not treat it as uniquely deduplicated spot exchange volume. The 'Tracked universe proxy' sums unique-symbol coin-list volumes, and named sectors are deliberately limited to the static symbol baskets defined in `phase1_monitor.py`. Sector membership is **not** authoritative, and similarly named symbols are omitted when duplicates occur. No claims about all DeFi, AI, NFT or RWA turnover can be made from these baskets alone.

For each segment, require the seven **distinct preceding UTC calendar-day snapshots**, the same symbols available for all seven days, at least 80% coverage of today's reported segment volume, and at least three common symbols for all sector and tracked-universe baskets (BTC and ETH allow one). Compare same-cohort current 24h volume with the arithmetic mean of its preceding seven snapshots. Output 'SURGE >=2x' or 'EXCEPTIONAL >=3x' only if adequate data is available. Blank/unknown/zero baseline values do not generate a spike.

**Warm-up:** Do not expect a surge signal until at least seven complete prior daily snapshot dates have accumulated on the production branch. The script currently writes *review-only* events to a report; **it does not send scheduled mobile alerts or notifications**. A later integration should verify the spot-only volume source, sector membership, intraday time alignment, data provenance, and duplicate notification handling before enabling push alerts.

### Confirmation labels — research flags only
A 'MULTI-SIGNAL CANDIDATE (NOT TECHNICALLY CONFIRMED)' requires all of:
- breakout score >=55;
- current daily trading volume >=2x its preceding seven-day mean;
- current daily engagement >=1.5x its preceding seven-day mean;
- positive broad social-post and contributor trends;
- seven-day price change between -5% and +25%;
- reported 24h snapshot volume >=$5m (volume proxy only);
- extension penalty <=8, spam penalty <=5;
- full historic data status `COMPLETE`.

Remaining rows receive 'UNCONFIRMED' or 'HIGH RISK / UNCONFIRMED', with explicit blockers. These are **screening labels**, not verified bullish trade signals or EMA confirmations; there are no order-book or bid-ask assessments and no new automatic breakout notifications. Existing stages remain unchanged.

## Local usage
`python phase1_monitor.py --reports-dir reports --data-dir data`

## Next steps before enabling automated market volume alerts
Validate source aggregation and spot/derivative definitions; replace static sector symbol baskets with vetted coin-ID based membership; introduce independent market-wide spot-volume history; confirm seven daily snapshots from stable time windows, publish separate event timestamps, and implement duplicate suppression plus notification plumbing. Keep volume and breakout alerts as separate channels.
