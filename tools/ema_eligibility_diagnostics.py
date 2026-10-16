#!/usr/bin/env python3
"""Explain missing EMA eligibility without altering historical inputs."""
import argparse
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import load_history_map, generate_daily_signal_rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="data")
    p.add_argument("--output", default="reports/ema_eligibility_diagnostics.csv.gz")
    a = p.parse_args()
    hist = load_history_map(a.data_dir)
    rows = generate_daily_signal_rows(hist)
    if rows.empty:
        raise SystemExit("No signal events found")
    for c in ["has_ema50", "has_ema100", "has_ema200", "bullish_alignment"]:
        rows[c] = rows[c].fillna(False).astype(bool)
    for c in ["ema_convergence", "distance_ema50", "distance_ema100"]:
        rows[c] = pd.to_numeric(rows[c], errors="coerce")
    rows["missing_ema200"] = ~rows.has_ema200
    rows["missing_convergence"] = rows.ema_convergence.isna()
    rows["convergence_gt_5pct"] = rows.ema_convergence.gt(.05)
    rows["alignment_false"] = ~rows.bullish_alignment
    rows["proximity_false"] = ~(rows.distance_ema50.abs().le(.05) | rows.distance_ema100.abs().le(.05))
    rows["combined_eligible"] = ~(rows.missing_convergence | rows.convergence_gt_5pct | rows.alignment_false | rows.proximity_false)
    output = Path(a.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(output, index=False, compression="gzip" if output.suffix == ".gz" else None)
    print(f"events={len(rows)} coins={rows.coin_id.nunique()}")
    for col in ["has_ema50", "has_ema100", "has_ema200", "missing_convergence", "convergence_gt_5pct", "alignment_false", "proximity_false", "combined_eligible"]:
        print(f"{col}={int(rows[col].sum())}")
    print(f"Saved {output}")

if __name__ == "__main__":
    main()
