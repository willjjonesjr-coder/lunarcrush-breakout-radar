"""Additional safety gates for sector identity, EMA confirmation and alert readiness.

This module never sends notifications or changes the production breakout score.
"""
import csv
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path


def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def by_id(rows):
    """Uniquely keyed LunarCrush ID snapshots, skipping ambiguous duplicate IDs."""
    grouped = {}
    for row in rows:
        asset_id = str(row.get("id") or "").strip()
        v = number(row.get("volume_24h"))
        if asset_id and v is not None and v >= 0:
            grouped.setdefault(asset_id, []).append(v)
    return {k: vals[0] for k, vals in grouped.items() if len(vals) == 1}


def vetted_sector_segments(snapshot, memberships):
    """Only registry IDs explicitly approved for a sector are eligible."""
    result = {}
    for name, ids in memberships.items():
        if not isinstance(ids, list) or any(not isinstance(i, str) or not i.strip() for i in ids):
            raise ValueError("Sector memberships must be lists of nonempty string coin IDs")
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate coin IDs in sector " + name)
        result[name] = {i: snapshot[i] for i in ids if i in snapshot}
    return result


def ema(values, period):
    alpha = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def technical_confirmation(path, as_of_date):
    """Conservative daily EMA50/100/200 check; requires 300 consecutive valid bars.

    Uses latest *completed* UTC daily bar, never a partial current-day candle.
    """
    result = {"technical_status": "INSUFFICIENT EMA HISTORY",
              "technical_reasons": "", "ema50": None, "ema100": None, "ema200": None}
    if not path.exists():
        result["technical_reasons"] = "No local price history"
        return result
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    daily = {}
    for r in rows:
        ts = r.get("time")
        p = number(r.get("close"))
        if ts is None or p is None or p <= 0:
            continue
        try:
            date = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            d = date.astimezone(timezone.utc).date()
        except ValueError:
            continue
        if d < as_of_date and d not in daily:
            daily[d] = p
    dates = sorted(daily)
    if len(dates) < 300 or dates[-1] != as_of_date - timedelta(days=1):
        result["technical_reasons"] = "Need 300 daily bars through latest completed UTC day"
        return result
    tail = dates[-300:]
    if any((b - a).days != 1 for a, b in zip(tail, tail[1:])):
        result["technical_reasons"] = "Daily price gaps"
        return result
    prices = [daily[d] for d in tail]
    e50, e100, e200 = (ema(prices, n) for n in (50, 100, 200))
    last = prices[-1]
    result.update(ema50=round(e50[-1], 10), ema100=round(e100[-1], 10),
                  ema200=round(e200[-1], 10))
    slope = e50[-1] > e50[-6]
    aligned = e50[-1] > e100[-1] > e200[-1]
    unextended = last <= e50[-1] * 1.10
    above_support = last >= e50[-1] * .97
    result["technical_status"] = ("EMA CONFIRMED" if aligned and slope and
                                    unextended and above_support else "EMA NOT CONFIRMED")
    result["technical_reasons"] = "; ".join(x for flag, x in [
        (aligned, "EMA ordering"), (slope, "EMA50 slope"),
        (unextended, "Price >10% above EMA50"), (above_support, "Price below EMA50 support")]
        if not flag)
    return result


def notification_readiness(segment, approved_source=False, technical_verified=False):
    """No automated delivery: readiness only, with explicit blocking explanations."""
    blockers = []
    if segment.get("status") != "READY":
        blockers.append("seven-day baseline or coverage not ready")
    if segment.get("classification") not in ("SURGE >=2x", "EXCEPTIONAL >=3x"):
        blockers.append("surge threshold not met")
    if not approved_source:
        blockers.append("not verified as exchange-wide spot or approved ID sector basket")
    if not technical_verified:
        blockers.append("independent confirmation not verified")
    blockers.append("push delivery and duplicate suppression not configured")
    return {"eligible_for_push": False, "reasons": blockers}
