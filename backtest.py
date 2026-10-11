import argparse
import csv
import os
from pathlib import Path

DEFAULT_THRESHOLDS = [20, 25, 30, 35, 40]
DEFAULT_HORIZONS = [7, 14, 30]


def parse_int_list(raw_value, default_list):
    if raw_value is None or str(raw_value).strip() == "":
        return default_list

    values = []
    for item in str(raw_value).split(","):
        item = item.strip()
        if item:
            values.append(int(item))
    return values if values else default_list


def passes_anti_pump(row, strategy):
    if strategy == "baseline":
    return True

    gain7 = row.get("prior_return_7")
    gain30 = row.get("prior_return_30")

    # Reject rows without sufficient historical data.
    if gain7 is None:
    return False

    gain7 = float(gain7)

    if strategy == "moderate":
    return gain7 <= 0.20

    if strategy == "strict":
    if gain30 is None:
    return False
    return gain7 <= 0.12 and float(gain30) <= 0.40

    raise ValueError(f"Unknown strategy: {strategy}")


def strategy_list(strategy):
    if strategy == "all":
        return ["baseline", "moderate", "strict"]
    return [strategy]


def normalize_row(row):
    """
    Convert a dict-like CSV row into a normalized row.
    Supports common names:
      - signal: signal_score, score, signal
      - return: return_7d, forward_return_7d, pnl_7d, ret_7d, etc.
    """
    normalized = {}

    for key in row:
        normalized[key.lower().strip()] = row[key]

    # Common signal key aliases
    signal = (
        normalized.get("signal_score")
        or normalized.get("signal")
        or normalized.get("score")
        or normalized.get("value")
    )

    normalized["signal"] = signal

    # Common return aliases by horizon
    return_columns = [
        "return",
        "ret",
        "pnl",
        "forward_return",
        "forward_ret",
        "performance",
    ]
    normalized["return"] = (
        normalized.get("return")
        or normalized.get("ret")
        or normalized.get("pnl")
        or normalized.get("performance")
    )

    return normalized


def extract_signal(row):
    value = row.get("signal")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_return(row, horizon):
    """
    Try multiple common column names for a return at a given horizon.
    """
    candidates = [
        f"return_{horizon}d",
        f"ret_{horizon}d",
        f"pnl_{horizon}d",
        f"forward_return_{horizon}d",
        f"forward_ret_{horizon}d",
        f"return_{horizon}",
        f"ret_{horizon}",
    ]

    for key in candidates:
        if row.get(key) is not None:
            try:
                return float(row.get(key))
            except (TypeError, ValueError):
                pass

    # Fallback to generic return column if it exists and only one horizon is being evaluated
    generic = row.get("return") or row.get("ret") or row.get("pnl")
    if generic is not None:
        try:
            return float(generic)
        except (TypeError, ValueError):
            pass

    return None


def iter_csv_rows(data_dir):
    if not data_dir:
        return []

    data_path = Path(data_dir)
    if not data_path.exists():
        return []

    rows = []
    for file_path in sorted(data_path.rglob("*.csv")):
        with file_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                continue
            for raw_row in reader:
                rows.append(normalize_row(raw_row))
    return rows


def compute_backtest(rows, strategy_name, threshold, horizon):
    """
    Simple backtest:
    - if signal >= threshold => trade signal is active
    - compute avg return over matched rows
    - return summary metrics
    """
    matched = []
    total_return = 0.0
    count = 0

    for row in rows:
        signal = extract_signal(row)
        if signal is None:
            continue

        ret = extract_return(row, horizon)
        if ret is None:
            continue

        if signal >= strategy_threshold(strategy_name, threshold):
            matched.append((signal, ret))
            total_return += float(ret)
            count += 1

    if count == 0:
        avg_return = 0.0
        hit_rate = 0.0
    else:
        avg_return = total_return / count
        hit_rate = sum(1 for _, r in matched if r > 0) / count

    return {
        "strategy": strategy_name,
        "threshold": threshold,
        "horizon_days": horizon,
        "signals": len(matched),
        "avg_return": avg_return,
        "hit_rate": hit_rate,
        "total_return": total_return,
    }


def write_csv(output_path, records):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "strategy",
        "threshold",
        "horizon_days",
        "signals",
        "avg_return",
        "hit_rate",
        "total_return",
    ]

    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def main():
    parser = argparse.ArgumentParser(description="Anti-pump backtest analysis")
    parser.add_argument("--data-dir", default="data", help="Directory containing backtest data")
    parser.add_argument("--threshold", type=float, default=20, help="Single signal threshold")
    parser.add_argument("--horizon", type=int, default=7, help="Single forward-return horizon in days")
    parser.add_argument("--output", default="reports/backtest.csv", help="Output CSV file path")
    parser.add_argument("--matrix", action="store_true", help="Run full matrix of thresholds/horizons")
    parser.add_argument("--thresholds", help="Comma-separated signal thresholds, e.g. '20,25,30'")
    parser.add_argument("--horizons", help="Comma-separated return horizons, e.g. '7,14,30'")
    parser.add_argument(
        "--strategy",
        choices=["all", "baseline", "moderate", "strict"],
        default="all",
        help="Strategy to test"
    )

    args = parser.parse_args()

    thresholds = parse_int_list(args.thresholds, DEFAULT_THRESHOLDS)
    horizons = parse_int_list(args.horizons, DEFAULT_HORIZONS)

    if args.matrix is False:
        thresholds = [int(args.threshold)]
        horizons = [int(args.horizon)]

    rows = iter_csv_rows(args.data_dir)

    results = []
    for strategy_name in strategy_list(args.strategy):
        for threshold in thresholds:
            for horizon in horizons:
                result = compute_backtest(rows, strategy_name, threshold, horizon)
                results.append(result)

    # If no data files were found, still write a valid CSV with no rows
    write_csv(args.output, results)

    print(f"Backtest complete. Wrote {len(results)} rows to {args.output}")
    print(f"Strategy: {args.strategy}")
    print(f"Thresholds: {thresholds}")
    print(f"Horizons: {horizons}")


if __name__ == "__main__":
    main()
