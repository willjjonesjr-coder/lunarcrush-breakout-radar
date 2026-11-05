#!/usr/bin/env python3
"""Compare a saved pre-optimization backtest.py with the current implementation.

Example (run from the repository root):
  git show <baseline-commit>:backtest.py > /tmp/backtest_before.py
  python tools/benchmark_backtest.py --baseline /tmp/backtest_before.py --data-dir data

Inputs are copied to a temporary directory; no source data or reports change.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backtest


def load_baseline(path):
    spec = importlib.util.spec_from_file_location("backtest_baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timed_run(module, folder, **kwargs):
    started = time.perf_counter()
    result = module.build_backtest_records(
        folder, [20, 25, 30, 35, 40], [7, 14, 30],
        ["baseline", "moderate", "strict"], **kwargs,
    )
    return result, time.perf_counter() - started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--data-dir", default="data", type=Path)
    parser.add_argument("--coins", default=10, type=int, help="Evenly spaced input files (default: 10)")
    args = parser.parse_args()
    paths = sorted(args.data_dir.glob("history_*.csv"))
    if args.coins < 1 or not paths:
        parser.error("Need at least one history file and --coins >= 1")
    positions = np.linspace(0, len(paths) - 1, min(args.coins, len(paths)), dtype=int)
    selected = [paths[i] for i in positions]
    baseline = load_baseline(args.baseline)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        data = root / "data"
        data.mkdir()
        manifest = {}
        for path in selected:
            shutil.copyfile(path, data / path.name)
            manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"Comparing all 45 combinations on {len(selected)} history files", flush=True)
        old, old_seconds = timed_run(baseline, data)
        print(f"Baseline calculation: {old_seconds:.3f}s", flush=True)
        new, new_seconds = timed_run(backtest, data)
        for expected, actual in zip(old, new):
            pd.testing.assert_frame_equal(pd.DataFrame(expected), pd.DataFrame(actual), check_exact=True)
        old_csv, new_csv = root / "old.csv", root / "new.csv"
        baseline.write_per_signal_csv(old_csv, old[1])
        streamed, stream_seconds = timed_run(backtest, data, per_signal_path=new_csv)
        assert streamed[1] == []
        for index in (0, 2):
            pd.testing.assert_frame_equal(pd.DataFrame(old[index]), pd.DataFrame(streamed[index]), check_exact=True)
        assert old_csv.read_bytes() == new_csv.read_bytes(), "Streamed detail CSV differs"
        for name, writer, rows_index in (("matrix", backtest.write_csv, 0), ("technical", backtest.write_tech_summary, 2)):
            writer(old_csv, old[rows_index])
            writer(new_csv, new[rows_index])
            assert old_csv.read_bytes() == new_csv.read_bytes(), f"{name} CSV differs"
        result = {
            "parity": "exact, including all three CSVs and row order",
            "baseline_seconds": old_seconds,
            "optimized_seconds": new_seconds,
            "optimized_streaming_seconds": stream_seconds,
            "calculation_speedup": old_seconds / new_seconds,
            "matrix_rows": len(new[0]), "detail_rows": len(new[1]),
            "input_files_sha256": manifest,
            "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        }
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
