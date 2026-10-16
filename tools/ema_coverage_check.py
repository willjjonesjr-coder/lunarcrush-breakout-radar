#!/usr/bin/env python3
"""Audit existing history coverage before EMA200 backfill."""
from pathlib import Path
import pandas as pd

for path in sorted(Path('data').glob('history_*.csv')):
    df = pd.read_csv(path)
    close = pd.to_numeric(df.get('close'), errors='coerce')
    n = int(close.notna().sum())
    print(f'{path.stem},{n},{n >= 200},{n >= 300}')
