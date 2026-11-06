#!/usr/bin/env python3
"""Audit EMA eligibility of the exact LunarCrush histories consumed by backtest.py.

Does not substitute exchange candles or change trading signals. A zero result in
a technical strategy is only interpretable if sufficient EMA histories exist.
"""
import argparse
import csv
import json
from pathlib import Path

from backtest import load_history_map


def audit(data_dir):
    histories = load_history_map(data_dir)
    result = {
        "history_source": str(data_dir),
        "histories_loaded": len(histories),
        "at_least_50_rows": 0,
        "at_least_100_rows": 0,
        "at_least_200_rows": 0,
        "at_least_300_rows": 0,
        "at_least_200_valid_closes": 0,
        "ema200_evaluable_histories": 0,
        "ema200_not_evaluable_histories": 0,
        "status": "unknown",
        "reason": "",
    }
    for history in histories.values():
        length = len(history)
        for span in (50, 100, 200, 300):
            if length >= span:
                result[f"at_least_{span}_rows"] += 1
        if "close" in history and history["close"].notna().sum() >= 200:
            result["at_least_200_valid_closes"] += 1
        # Keep row-based availability identical to backtest_features.py, while
        # distinguishing histories with no numeric endpoint price.
        if length >= 200 and "close" in history and history["close"].notna().any():
            result["ema200_evaluable_histories"] += 1
    result["ema200_not_evaluable_histories"] = (
        result["histories_loaded"] - result["ema200_evaluable_histories"]
    )
    if not result["histories_loaded"]:
        result["status"] = "no_histories"
        result["reason"] = "No readable backtest history files were loaded."
    elif not result["ema200_evaluable_histories"]:
        result["status"] = "insufficient_history"
        result["reason"] = (
            "No input history has the 200 observations required by the EMA200 "
            "backtest conditions. Zero convergence/alignment signals are "
            "unavailable-data results, not negative strategy evidence."
        )
    else:
        result["status"] = "eligible_histories_present"
        result["reason"] = (
            "Some inputs meet the EMA200 row requirement. Inspect actual "
            "convergence/alignment distributions to explain any zero signals."
        )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="reports/backtest_ema_eligibility.json")
    args = parser.parse_args()
    result = audit(args.data_dir)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
