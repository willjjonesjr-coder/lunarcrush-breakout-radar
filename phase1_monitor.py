"""Phase 1: conservative daily volume proxies and independent breakout confirmation labels.

No new API requests. 'Market' is a tracked-LunarCrush-universe proxy, NOT
exchange-wide spot volume. Sector memberships are explicit watchlist baskets.
No notification is sent automatically by this script.
"""
import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from phase2_safeguards import by_id, vetted_sector_segments, technical_confirmation, notification_readiness, resolve_ema_source

SECTORS = {
    "DeFi basket": ["UNI", "AAVE", "MKR", "COMP", "CRV", "SNX", "SUSHI", "JST", "DYDX", "LDO"],
    "AI basket": ["FET", "RENDER", "RNDR", "TAO", "AKT", "VIRTUAL", "AI16Z", "ARKM", "GRASS"],
    "NFT/Gaming basket": ["APE", "BLUR", "IMX", "GALA", "SAND", "MANA", "AXS", "ENJ", "MAGIC"],
    "Layer 1 basket": ["ETH", "SOL", "ADA", "AVAX", "NEAR", "SUI", "APT", "ATOM", "DOT"],
    "Layer 2 basket": ["ARB", "OP", "STRK", "ZK", "MANTA", "METIS"],
    "Memecoin basket": ["DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI", "BRETT"],
    "RWA basket": ["ONDO", "LINK", "PENDLE", "POLYX", "CFG", "MPL", "RIO"],
}


def valid_number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def volume_snapshot(rows):
    """Only unique symbols with valid nonnegative volume; collisions omitted."""
    grouped = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        volume = valid_number(row.get("volume_24h"))
        if symbol and volume is not None and volume >= 0:
            grouped.setdefault(symbol, []).append(volume)
    return {k: v[0] for k, v in grouped.items() if len(v) == 1}


def segment_snapshot(volumes):
    return {"Tracked universe proxy": dict(volumes),
            "BTC": {k: volumes[k] for k in ("BTC",) if k in volumes},
            "ETH": {k: volumes[k] for k in ("ETH",) if k in volumes},
            **{name: {k: volumes[k] for k in symbols if k in volumes}
               for name, symbols in SECTORS.items()}}


def evaluate_segment(name, current, baseline, required_days=7):
    """Use a fixed SAME-COHORT basket across all seven baseline dates."""
    result = {"segment": name, "source": "LunarCrush 24h reported-volume proxy",
              "status": "INSUFFICIENT BASELINE", "multiple": None,
              "current_volume": None, "baseline_volume": None,
              "coverage": 0, "top_contributors": [],
              "classification": "NO ALERT"}
    if len(baseline) != required_days or not current:
        return result
    common = set(current)
    for day in baseline:
        common.intersection_update(day)
    current_total = sum(current.values())
    covered_total = sum(current[s] for s in common)
    coverage = covered_total / current_total if current_total > 0 else 0
    result["coverage"] = round(coverage, 4)
    # Small baskets may legitimately contain 1 symbol; sector baskets require 3.
    minimum = 1 if name in ("BTC", "ETH") else 3
    if len(common) < minimum or coverage < 0.8:
        result["status"] = "INSUFFICIENT COVERAGE"
        return result
    samples = [sum(day[s] for s in common) for day in baseline]
    base = sum(samples) / required_days
    if base <= 0:
        result["status"] = "ZERO BASELINE"
        return result
    multiple = covered_total / base
    result.update(status="READY", multiple=round(multiple, 4),
                  current_volume=round(covered_total, 2),
                  baseline_volume=round(base, 2),
                  top_contributors=[{"symbol": s, "volume": round(current[s], 2)}
                                    for s in sorted(common, key=lambda s: current[s], reverse=True)[:5]],
                  classification=("EXCEPTIONAL >=3x" if multiple >= 3 else
                                  "SURGE >=2x" if multiple >= 2 else "NO ALERT"))
    return result


def confirmation(row):
    """Report-only label. It is NOT an EMA-confirmed trading signal."""
    score = valid_number(row.get("breakout_score"))
    vol = valid_number(row.get("volume_daily_accel"))
    engagement = valid_number(row.get("engagement_daily_accel"))
    social = valid_number(row.get("social_accel"))
    contrib = valid_number(row.get("contributor_accel"))
    price = valid_number(row.get("price_change_7d"))
    liquidity = valid_number(row.get("volume_24h_snapshot"))
    extension = valid_number(row.get("extension_penalty"))
    spam = valid_number(row.get("spam_penalty"))
    status = str(row.get("data_status") or "")
    blockers = []
    if score is None or score < 55: blockers.append("score")
    if vol is None or vol < 1: blockers.append("daily volume <2x")
    if engagement is None or engagement < .5: blockers.append("daily engagement <1.5x")
    if social is None or social <= 0 or contrib is None or contrib <= 0:
        blockers.append("social participation")
    if price is None or not -.05 <= price <= .25: blockers.append("7d price/extension")
    if liquidity is None or liquidity < 5_000_000: blockers.append("volume proxy < $5m")
    if extension is None or extension > 8 or spam is None or spam > 5:
        blockers.append("extension/spam")
    if status != "COMPLETE": blockers.append("history incomplete")
    if not blockers:
        label = "MULTI-SIGNAL CANDIDATE (NOT TECHNICALLY CONFIRMED)"
    elif (price is not None and price > .25) or (liquidity is not None and liquidity < 5_000_000):
        label = "HIGH RISK / UNCONFIRMED"
    else:
        label = "UNCONFIRMED"
    return label, "; ".join(blockers)


def run(reports, data, as_of=None):
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    data.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    snapshots_file = data / "volume_snapshot_history.json"
    history = json.loads(snapshots_file.read_text()) if snapshots_file.exists() else {}
    with (data / "universe_latest.csv").open(newline="") as f:
        latest = volume_snapshot(csv.DictReader(f))
    # Overwrite duplicate same-day captures rather than double-counting.
    history[as_of] = latest
    history = dict(sorted(history.items())[-40:])
    snapshots_file.write_text(json.dumps(history, sort_keys=True, indent=2) + "\n")
    from datetime import date, timedelta
    today = date.fromisoformat(as_of)
    days = [(today - timedelta(days=d)).isoformat() for d in range(7, 0, -1)]
    segments = segment_snapshot(latest)
    # Existing symbol baskets remain visible as research-only, not validated alerts.
    # New explicitly approved coin-ID baskets are tracked independently.
    registry = Path("config/sector_coin_ids.json")
    memberships = json.loads(registry.read_text()) if registry.exists() else {}
    id_history_path = data / "volume_snapshot_history_by_id.json"
    id_history = json.loads(id_history_path.read_text()) if id_history_path.exists() else {}
    with (data / "universe_latest.csv").open(newline="") as f:
        id_latest = by_id(csv.DictReader(f))
    id_history[as_of] = id_latest
    id_history = dict(sorted(id_history.items())[-40:])
    id_history_path.write_text(json.dumps(id_history, sort_keys=True, indent=2) + "\n")
    id_segments = vetted_sector_segments(id_latest, memberships)
    observations = []
    for name, current in segments.items():
        past = [segment_snapshot(history[d])[name] for d in days] if all(d in history for d in days) else []
        observations.append(evaluate_segment(name, current, past))
    for name, current in id_segments.items():
        prior = [vetted_sector_segments(id_history[d], memberships)[name]
                 for d in days] if all(d in id_history for d in days) else []
        observation = evaluate_segment(name + " (vetted IDs)", current, prior)
        observation["membership_source"] = "config/sector_coin_ids.json"
        observations.append(observation)
    for observation in observations:
        observation["notification_readiness"] = notification_readiness(observation)
        if "(vetted IDs)" not in observation["segment"]:
            observation["coverage_note"] = "Unverified symbol basket or non-spot market proxy"
    volume_report = {"as_of": as_of, "baseline_days": days,
                     "data_source": "LunarCrush coin-list snapshots (reported 24h volume)",
                     "scope_warning": "Tracked-universe and named-sector baskets are NOT comprehensive market spot volume, nor deduplicated exchange trade volume.",
                     "alert_policy": "Review-only. Notify only after independent verification; no automated notifications.",
                     "segments": observations}
    (reports / "volume_surge_latest.json").write_text(json.dumps(volume_report, indent=2) + "\n")
    p = reports / "breakout_radar.json"
    rows = json.loads(p.read_text())
    for row in rows:
        row["confirmation_label"], row["confirmation_blockers"] = confirmation(row)
        source_path, source_label = resolve_ema_source(row.get("id"), data)
        info = technical_confirmation(source_path, today)
        info["ema_history_source"] = source_label
        row.update(info)
        row["confirmation_label"] += " / " + info["technical_status"]
    p.write_text(json.dumps(rows, allow_nan=False) + "\n")
    c = reports / "breakout_radar.csv"
    with c.open(newline="") as f:
        reader = csv.DictReader(f)
        old = list(reader)
        fields = list(reader.fieldnames)
    for col in ("confirmation_label", "confirmation_blockers"):
        if col not in fields: fields.append(col)
    for col in ("technical_status", "technical_reasons", "ema50", "ema100", "ema200", "ema_history_source"):
        if col not in fields: fields.append(col)
    for row in old:
        row["confirmation_label"], row["confirmation_blockers"] = confirmation(row)
        info = technical_confirmation(data / f"history_{row.get('id')}.csv", today)
        row.update(info)
        row["confirmation_label"] += " / " + info["technical_status"]
    with c.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(old)
    from collections import Counter
    counts = Counter(r.get("technical_status", "UNKNOWN") for r in rows)
    sources = Counter(r.get("ema_history_source", "UNKNOWN") for r in rows)
    (reports / "ema_coverage_latest.json").write_text(json.dumps({
        "as_of": as_of, "analyzed": len(rows), "technical_status_counts": dict(counts),
        "ema_history_source_counts": dict(sources),
        "note": "Exchange candles require verified coin-ID mapping and matching backfill inventory; no symbols inferred."},
        indent=2) + "\\n")
    print("EMA coverage:", dict(counts), "sources:", dict(sources))
    print("Phase 1: confirmation labels added; segment volume snapshots evaluated (no notifications)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    run(Path(args.reports_dir), Path(args.data_dir))
