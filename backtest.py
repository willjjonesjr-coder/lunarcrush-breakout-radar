import argparse
import csv
import json
import os
import subprocess
from pathlib import Path

DEFAULT_THRESHOLDS = [20, 25, 30, 35, 40]
DEFAULT_HORIZONS = [7, 14, 30]


def parse_int_list(raw_value, default_list):
    """Parse threshold/horizon input values from JSON, CSV, or a plain scalar."""
    if raw_value is None or str(raw_value).strip() == "":
        return list(default_list)

    value = raw_value
    if isinstance(value, list):
        parsed = value
    else:
        value_text = str(value).strip()
        if value_text == "":
            return list(default_list)

        # JSON array takes precedence (e.g. '[20, 35]' or '[]')
        try:
            parsed = json.loads(value_text)
        except Exception:
            parsed = [part.strip() for part in value_text.strip("[]").split(",") if part.strip()]

    if parsed is None:
        return list(default_list)

    if isinstance(parsed, (int, float)):
        parsed = [parsed]

    values = []
    try:
        for item in parsed:
            values.append(int(item))
    except (TypeError, ValueError):
        return list(default_list)

    return values if values else list(default_list)


def get_commit_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return os.environ.get("GITHUB_SHA", "unknown")


def print_matrix_debug(thresholds, horizons):
    print(f"commit: {get_commit_sha()}")
    print(f"parsed thresholds: {thresholds}")
    print(f"parsed horizons: {horizons}")
    print(f"expanded combinations: {len(thresholds) * len(horizons)}")


def validate_matrix_inputs(thresholds_raw, horizons_raw, matrix_flag, single_threshold, single_horizon, expected_min_combinations=45):
    """Resolve thresholds/horizons while preserving explicit CLI inputs."""
    thresholds = parse_int_list(thresholds_raw, DEFAULT_THRESHOLDS)
    horizons = parse_int_list(horizons_raw, DEFAULT_HORIZONS)

    if thresholds_raw is None and not matrix_flag:
        thresholds = [int(single_threshold)]
    if horizons_raw is None and not matrix_flag:
        horizons = [int(single_horizon)]

    if thresholds_raw is None and matrix_flag:
        thresholds = list(DEFAULT_THRESHOLDS)
    if horizons_raw is None and matrix_flag:
        horizons = list(DEFAULT_HORIZONS)

    if not thresholds or not horizons:
        raise SystemExit("ERROR: thresholds and horizons must be non-empty lists.")

    try:
        thresholds = [int(x) for x in thresholds]
        horizons = [int(x) for x in horizons]
    except (TypeError, ValueError):
        raise SystemExit("ERROR: thresholds and horizons must contain integers only.")

    if any(t <= 0 for t in thresholds) or any(h <= 0 for h in horizons):
        raise SystemExit("ERROR: thresholds and horizons must be positive integers.")

    combos = len(thresholds) * len(horizons)
    print_matrix_debug(thresholds, horizons)

    if combos < expected_min_combinations:
        raise SystemExit(
            f"ERROR: expected at least {expected_min_combinations} matrix combinations, but got {combos}. "
            "This usually means the requested thresholds/horizons were reduced or parsed incorrectly."
        )

    return thresholds, horizons


def assert_baseline_signals(baseline_signal_count):
    print(f"baseline signals found: {baseline_signal_count}")
    if baseline_signal_count == 0:
        raise SystemExit("ERROR: baseline produced 0 historical signals — aborting backtest run.")


def strategy_threshold(strategy, threshold):
    """
    Adjust threshold by strategy.
    - baseline: same threshold
    - moderate: slightly looser
    - strict: stricter
    """
    if strategy == "baseline":
        return threshold
    if strategy == "moderate":
        return max(0, threshold - 5)
    if strategy == "strict":
        return max(0, threshold + 5)
    return threshold


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
    parser.add_argument("--thresholds", default=None, help="Comma-separated or JSON signal thresholds, e.g. '20,25,30' or '[20,25,30]'")
    parser.add_argument("--horizons", default=None, help="Comma-separated or JSON return horizons, e.g. '7,14,30' or '[7,14,30]'")
    parser.add_argument("--min-combinations", type=int, default=45, help="Abort if expanded matrix is smaller than this")
    parser.add_argument(
        "--strategy",
        choices=["all", "baseline", "moderate", "strict"],
        default="all",
        help="Strategy to test"
    )

    args = parser.parse_args()

    thresholds, horizons = validate_matrix_inputs(
        args.thresholds,
        args.horizons,
        args.matrix,
        args.threshold,
        args.horizon,
        expected_min_combinations=args.min_combinations,
    )

    rows = iter_csv_rows(args.data_dir)

    results = []
    baseline_signal_count = 0
    for strategy_name in strategy_list(args.strategy):
        for threshold in thresholds:
            for horizon in horizons:
                result = compute_backtest(rows, strategy_name, threshold, horizon)
                results.append(result)
                if strategy_name == "baseline":
                    baseline_signal_count += result["signals"]

    if args.strategy in {"all", "baseline"}:
        assert_baseline_signals(baseline_signal_count)

    # If no data files were found, still write a valid CSV with no rows
    write_csv(args.output, results)

    print(f"Backtest complete. Wrote {len(results)} rows to {args.output}")
    print(f"Strategy: {args.strategy}")
    print(f"Thresholds: {thresholds}")
    print(f"Horizons: {horizons}")


if __name__ == "__main__":
    main()
