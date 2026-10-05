import argparse
from pathlib import Path

import numpy as np
import pandas as pd


FEATURES = [
    "contributors_active",
    "contributors_created",
    "interactions",
    "posts_active",
    "posts_created",
    "sentiment",
    "spam",
    "close",
    "galaxy_score",
    "social_dominance",
    "volume_24h",
]


def load_history(path):
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for c in FEATURES:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("time").drop_duplicates("time").reset_index(drop=True)


def rolling_accel(s, short=7, base=23):
    short_mean = s.rolling(short, min_periods=3).mean()
    base_mean = s.shift(short).rolling(base, min_periods=8).mean()
    return short_mean / base_mean.replace(0, np.nan) - 1


def make_features(h):
    x = h.copy()

    x["social_accel"] = rolling_accel(x["posts_active"])
    x["contributor_accel"] = rolling_accel(x["contributors_active"])
    x["engagement_accel"] = rolling_accel(x["interactions"])
    x["volume_accel"] = rolling_accel(x["volume_24h"])

    x["sentiment_change"] = x["sentiment"] - x["sentiment"].shift(7)
    x["social_dom_change"] = (
        x["social_dominance"] / x["social_dominance"].shift(7).replace(0, np.nan) - 1
    )

    x["price_change_7d"] = x["close"] / x["close"].shift(7) - 1

    social = x[
        ["social_accel", "contributor_accel", "engagement_accel"]
    ].mean(axis=1)

    x["social_price_divergence"] = social - x["price_change_7d"].clip(lower=0)

    # Cross-sectional normalization isn't available inside one coin's history,
    # so this backtest uses fixed thresholds for the initial research pass.
    x["signal_score"] = (
        25 * x["social_accel"].clip(-1, 3).fillna(0) / 3 +
        15 * x["contributor_accel"].clip(-1, 3).fillna(0) / 3 +
        15 * x["engagement_accel"].clip(-1, 3).fillna(0) / 3 +
        10 * (x["sentiment_change"].clip(-30, 30).fillna(0) / 30) +
        10 * x["social_dom_change"].clip(-1, 3).fillna(0) / 3 +
        10 * x["volume_accel"].clip(-1, 3).fillna(0) / 3 +
        15 * x["social_price_divergence"].clip(-1, 3).fillna(0) / 3
    )

    return x

def events_for(x, threshold, horizon, coin):
    if horizon < 1:
        raise ValueError('Horizon must be at least 1')
    price = x['close']
    future = price.shift(-horizon) / price - 1
    drawdown = (price.rolling(horizon, min_periods=horizon).min().shift(-horizon) / price - 1).clip(upper=0)
    valid = (x['signal_score'] >= threshold) & (price > 0) & np.isfinite(future) & np.isfinite(drawdown)
    out = pd.DataFrame({'signal_time': x['time'], 'signal_score': x['signal_score'],
                        'entry_price': price, 'forward_return': future, 'max_forward_drawdown': drawdown})[valid].copy()
    out['coin_file'] = coin
    out['threshold'] = threshold
    out['horizon'] = horizon
    return out


def summarize(events):
    r = events['forward_return']
    dd = events['max_forward_drawdown']
    return {'signals': len(events), 'coins_with_signals': events['coin_file'].nunique(),
            'hit_10pct': (r >= .1).mean() if len(r) else np.nan,
            'hit_20pct': (r >= .2).mean() if len(r) else np.nan,
            'hit_50pct': (r >= .5).mean() if len(r) else np.nan,
            'mean_forward_return': r.mean(), 'median_forward_return': r.median(),
            'worst_forward_return': r.min(), 'mean_max_forward_drawdown': dd.mean(),
            'worst_max_forward_drawdown': dd.min()}


def evaluate(h, threshold, horizon):
    events = events_for(make_features(h), threshold, horizon, 'coin')
    return summarize(events) if len(events) else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--threshold', type=float, default=25)
    parser.add_argument('--horizon', type=int, default=14)
    parser.add_argument('--output', default='reports/backtest.csv')
    parser.add_argument('--matrix', action='store_true')
    parser.add_argument('--thresholds', default='20,25,30,35,40')
    parser.add_argument('--horizons', default='7,14,30')
    args = parser.parse_args()
    thresholds = sorted(set(float(t) for t in args.thresholds.split(','))) if args.matrix else [args.threshold]
    horizons = sorted(set(int(t) for t in args.horizons.split(','))) if args.matrix else [args.horizon]
    if not thresholds or not horizons or any(h < 1 for h in horizons) or not all(np.isfinite(t) for t in thresholds):
        parser.error('Use finite thresholds and positive horizons')
    paths = sorted(Path(args.data_dir).glob('history_*.csv'))
    if not paths:
        raise SystemExit('No history files found. Run scanner first.')
    histories = {}
    for path in paths:
        try:
            h = load_history(path)
            histories[path.name] = make_features(h)
        except Exception as exc:
            print(f'[WARN] Skipping {path.name}: {exc}')
    if not histories:
        raise SystemExit('No usable histories.')
    all_events, per_coin, matrix = [], [], []
    for threshold in thresholds:
        for horizon in horizons:
            chunks, eligible = [], 0
            for coin, h in histories.items():
                if len(h) < max(45, horizon + 14):
                    continue
                eligible += 1
                events = events_for(h, threshold, horizon, coin)
                chunks.append(events)
                per_coin.append(dict(threshold=threshold, horizon=horizon, coin_file=coin, **summarize(events)))
            if chunks:
                events = pd.concat(chunks, ignore_index=True)
            else:
                events = events_for(next(iter(histories.values())).iloc[:0], threshold, horizon, '')
            all_events.append(events)
            matrix.append(dict(threshold=threshold, horizon=horizon, coins_loaded=len(histories),
                               coins_eligible=eligible, **summarize(events)))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = output.with_suffix('')
    coin_table = pd.DataFrame(per_coin)
    coin_table.to_csv(output, index=False)
    coin_table.to_csv(str(prefix) + '_per_coin.csv', index=False)
    pd.concat(all_events, ignore_index=True).to_csv(str(prefix) + '_events.csv', index=False)
    summary = pd.DataFrame(matrix)
    summary.to_csv(str(prefix) + '_matrix.csv', index=False)
    print('Signal-weighted results (each qualifying observation has equal weight):')
    print(summary.to_string(index=False))
    print('Research only: overlapping signals, current-universe selection bias, revised data; no fees/slippage. Horizons count observations, not calendar days. Drawdown is daily-close loss relative to entry.')


if __name__ == '__main__':
    main()
