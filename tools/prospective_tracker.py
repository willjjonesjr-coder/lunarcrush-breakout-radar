"""Prospective signal ledger. No new API calls; no backfilled candidate selection.

Stores immutable scan snapshots and updates outcomes only when exact UTC
calendar-date prices are available. Missing data remains pending.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path("data")
REPORTS = Path("reports")
ROOT = REPORTS / "prospective"
SNAPSHOTS = ROOT / "snapshots"
SNAPSHOTS.mkdir(parents=True, exist_ok=True)
HORIZONS = (1, 3, 7, 14, 30)

scored = pd.read_csv(REPORTS / "full_scored_candidates.csv", dtype={"id": str})
if scored.empty or not {"id", "breakout_score", "stage", "last_time"}.issubset(scored):
    raise RuntimeError("Missing full scored candidate data")
diagnostics = json.loads((REPORTS / "scan_diagnostics.json").read_text())
# Record scan date separately from last complete daily market-data bucket.
scan_time = pd.Timestamp(diagnostics["as_of_utc"])
scan_date = scan_time.normalize()
stamp = scan_time.strftime("%Y%m%dT%H%M%SZ")
snapshot_path = SNAPSHOTS / f"full_scored_{stamp}.csv"
if snapshot_path.exists():
    raise RuntimeError(f"Snapshot already exists: {snapshot_path}")
scored.insert(0, "scan_timestamp_utc", scan_time.isoformat())
scored.insert(1, "signal_date_utc", scan_date.date().isoformat())
scored.to_csv(snapshot_path, index=False)

# One row per scan/asset/horizon. Never overwrite past features or scores.
ledger_path = ROOT / "signal_ledger.csv"
ledger = pd.read_csv(ledger_path, dtype={"id": str}) if ledger_path.exists() else pd.DataFrame()
rows = []
for coin in scored.itertuples(index=False):
    for horizon in HORIZONS:
        rows.append({
            "scan_timestamp_utc": scan_time.isoformat(),
            "signal_date_utc": scan_date.date().isoformat(),
            "id": str(coin.id), "symbol": str(coin.symbol),
            "score": float(coin.breakout_score), "stage": str(coin.stage),
            "asset_type": str(getattr(coin, "asset_type", "unverified")),
            "normalization_version": str(getattr(coin, "normalization_version", "unknown")),
            "overextended_flag": bool(getattr(coin, "overextended_flag", False)),
            "low_liquidity_flag": bool(getattr(coin, "low_liquidity_flag", False)),
            "horizon_days": horizon, "status": "pending",
            "entry_price": np.nan, "exit_price": np.nan,
            "forward_return": np.nan, "btc_return": np.nan, "eth_return": np.nan,
            "excess_btc": np.nan, "excess_eth": np.nan,
            "max_adverse_excursion": np.nan, "max_favorable_excursion": np.nan,
            "quality_flags": ""
        })
new = pd.DataFrame(rows)
ledger = pd.concat([ledger, new], ignore_index=True)
ledger = ledger.drop_duplicates(["scan_timestamp_utc", "id", "horizon_days"], keep="first")

universe = pd.read_csv(DATA / "universe_latest.csv", dtype={"id": str})
symbols = universe.drop_duplicates("id").set_index("id").symbol.to_dict()
price_cache = {}
def series_for(cid):
    cid = str(cid)
    if cid not in price_cache:
        path = DATA / f"history_{cid}.csv"
        if not path.exists():
            price_cache[cid] = None
        else:
            h = pd.read_csv(path, usecols=lambda c: c in ("time", "close"))
            if not {"time", "close"}.issubset(h):
                price_cache[cid] = None
            else:
                h["date"] = pd.to_datetime(h.time, utc=True).dt.normalize()
                h["close"] = pd.to_numeric(h.close, errors="coerce")
                price_cache[cid] = h.dropna().sort_values("date").drop_duplicates("date", keep="last").set_index("date").close
    return price_cache[cid]

bench_ids = {}
for ticker in ("BTC", "ETH"):
    matches = [cid for cid, sym in symbols.items() if str(sym).upper() == ticker and series_for(cid) is not None]
    bench_ids[ticker] = matches[0] if len(matches) == 1 else None

def price_return(cid, start, end):
    s = series_for(cid) if cid is not None else None
    if s is None or start not in s.index or end not in s.index:
        return np.nan
    p0, p1 = s.loc[start], s.loc[end]
    if not np.isfinite(p0) or p0 <= 0 or not np.isfinite(p1) or p1 < 0:
        return np.nan
    return float(p1/p0-1)

# Use the FIRST fully closed daily candle AFTER scan for entry. This avoids
# using the already-closed pre-scan candle as an executable entry price.
# Latest closed daily bucket is strictly before the current UTC day.
latest_closed = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)
for i, row in ledger.loc[ledger.status.eq("pending")].iterrows():
    scan_day = pd.Timestamp(row.signal_date_utc, tz="UTC")
    entry_day = scan_day + pd.Timedelta(days=1)
    exit_day = entry_day + pd.Timedelta(days=int(row.horizon_days))
    if exit_day > latest_closed:
        continue
    s = series_for(row.id)
    if s is None or entry_day not in s.index or exit_day not in s.index:
        continue
    window = pd.date_range(entry_day, exit_day, freq="D", tz="UTC")
    if not window.isin(s.index).all():
        continue
    p = s.reindex(window)
    entry = float(p.iloc[0])
    exit_price = float(p.iloc[-1])
    if not np.isfinite(entry) or entry <= 0 or not np.isfinite(exit_price) or exit_price < 0:
        continue
    r = exit_price/entry - 1
    flags = []
    if r > 10: flags.append("EXTREME_GAIN_GT_1000PCT")
    if row.asset_type != "unverified": flags.append("NON_ALTCOIN_ASSET_TYPE")
    ledger.at[i, "entry_price"] = entry
    ledger.at[i, "exit_price"] = exit_price
    ledger.at[i, "forward_return"] = r
    ledger.at[i, "max_adverse_excursion"] = float((p/entry-1).min())
    ledger.at[i, "max_favorable_excursion"] = float((p/entry-1).max())
    ledger.at[i, "btc_return"] = price_return(bench_ids["BTC"],entry_day,exit_day)
    ledger.at[i, "eth_return"] = price_return(bench_ids["ETH"],entry_day,exit_day)
    ledger.at[i, "excess_btc"] = r - ledger.at[i, "btc_return"]
    ledger.at[i, "excess_eth"] = r - ledger.at[i, "eth_return"]
    ledger.at[i, "quality_flags"] = "|".join(flags)
    ledger.at[i, "status"] = "flagged" if flags else "matured"

ledger.to_csv(ledger_path, index=False)
mature = ledger[ledger.status.eq("matured")].copy()
summary = {
    "snapshot": str(snapshot_path), "scored_candidates": len(scored),
    "ledger_rows": len(ledger), "matured": len(mature),
    "pending": int(ledger.status.eq("pending").sum()),
    "flagged": int(ledger.status.eq("flagged").sum()),
    "benchmark_ids": bench_ids,
    "by_horizon_and_version": [],
    "limitations": [
        "First fully closed post-scan UTC candle used as entry proxy; not a tradable execution price.",
        "Historical daily close data cannot establish intraday drawdown or slippage.",
        "Coin history may not be refreshed once an asset rotates out; outcomes remain pending.",
        "Only historically scanned assets are included, not the entire coin market.",
        "No fees, liquidity-based sizing, or survivorship corrections."
    ]
}
for (horizon, version), g in mature.groupby(["horizon_days","normalization_version"]):
    summary["by_horizon_and_version"].append({
        "horizon_days": int(horizon), "normalization_version": str(version),
        "n": len(g), "assets": int(g.id.nunique()),
        "median_return": float(g.forward_return.median()),
        "hit_rate": float((g.forward_return>0).mean()),
        "median_excess_btc": float(g.excess_btc.median()) if g.excess_btc.notna().any() else None,
        "median_excess_eth": float(g.excess_eth.median()) if g.excess_eth.notna().any() else None,
        "median_max_adverse_excursion": float(g.max_adverse_excursion.median())
    })
(ROOT / "prospective_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps({k: summary[k] for k in ("scored_candidates","ledger_rows","matured","pending","flagged")}, indent=2))
