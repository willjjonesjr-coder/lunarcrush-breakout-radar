"""Conservative undervaluation research overlay: valuation evidence, not a price target.

Runs on existing published reports only. No external API requests, no score
changes to breakout model, and no automatic notifications.
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def num(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def clipped(value, lo, hi):
    return max(lo, min(hi, value))


def positive(value):
    n = num(value)
    return n if n is not None and n > 0 else None


def drawdown_status(row):
    p30 = num(row.get("price_change_30d"))
    p7 = num(row.get("price_change_7d"))
    if p30 is None or p7 is None:
        return "PRICE HISTORY UNKNOWN"
    if p30 <= -.30 and p7 <= -.05:
        return "HEAVY SELL-OFF (NOT VALUATION)"
    if p30 <= -.20:
        return "SELL-OFF WATCH (NOT VALUATION)"
    return "NO DEEP DISCOUNT SIGNAL"


def financials_ok(row):
    return (row.get("fundamentals_mapping") == "exact_name_and_symbol"
            and row.get("fundamentals_confidence") == "MODERATE"
            and row.get("fundamentals_sector") not in (None, "", "nan")
            and positive(row.get("fundamentals_holder_revenue_365d")) is not None
            and positive(row.get("fundamentals_market_cap_to_holder_revenue_365d")) is not None
            and num(row.get("fundamentals_fees_growth_30d")) is not None
            and num(row.get("fundamentals_revenue_growth_30d")) is not None
            and num(row.get("fundamentals_holder_revenue_growth_30d")) is not None
            and num(row.get("fundamentals_fdv_to_market_cap")) is not None
            and num(row.get("price_change_30d")) is not None)


def peer_multiples(rows):
    # Comparable coin/token economics within the SAME DefiLlama sector.
    groups = defaultdict(list)
    for row in rows:
        if financials_ok(row):
            groups[str(row["fundamentals_sector"])].append(row)
    return {sector: group for sector, group in groups.items() if len(group) >= 3}


def evaluate(rows):
    peers = peer_multiples(rows)
    results = []
    for row in rows:
        r = dict(row)
        sector = str(row.get("fundamentals_sector") or "")
        r["undervaluation_price_context"] = drawdown_status(row)
        r["undervaluation_score"] = None
        r["undervaluation_classification"] = "UNRATED"
        r["undervaluation_confidence"] = "INSUFFICIENT"
        r["undervaluation_peer_count"] = len(peers.get(sector, []))
        r["undervaluation_sector"] = sector or "UNKNOWN"
        r["undervaluation_reasons"] = ""
        if not financials_ok(row):
            r["undervaluation_reasons"] = "Missing verified identity, holder value capture, 365d holder revenue, economic growth, supply, or price history"
            results.append(r)
            continue
        group = peers.get(sector)
        if group is None:
            r["undervaluation_reasons"] = "Fewer than 3 independently assessed peers with comparable holder-revenue economics"
            results.append(r)
            continue
        multiple = positive(row.get("fundamentals_market_cap_to_holder_revenue_365d"))
        peer_values = sorted(positive(x["fundamentals_market_cap_to_holder_revenue_365d"]) for x in group)
        # Fraction of peers trading at HIGHER multiple; cheapness is sector-relative,
        # not absolute fair value. Includes the subject to avoid small-sample exaggeration.
        cheaper_rank = sum(x > multiple for x in peer_values) / len(peer_values)
        valuation_component = 25 * cheaper_rank
        fees = num(row.get("fundamentals_fees_growth_30d"))
        revenue = num(row.get("fundamentals_revenue_growth_30d"))
        holder = num(row.get("fundamentals_holder_revenue_growth_30d"))
        # Growth ratio capped, no fabricated zero for missing data.
        resilience = sum(clipped(0.5 + x, 0, 1) for x in (fees, revenue, holder)) / 3
        fundamentals_component = 30 * resilience
        # Strong sell-off earns more potential-dislocation points only when
        # financial evidence is complete; it is NOT proof of intrinsic value.
        p30 = num(row.get("price_change_30d"))
        dislocation_component = 15 * clipped((-p30) / .45, 0, 1)
        # Basic liquidity is a volume proxy, not depth or spreads.
        volume = num(row.get("volume_24h_snapshot"))
        liquidity_component = 10 if volume is not None and volume >= 50_000_000 else (
            6 if volume is not None and volume >= 5_000_000 else 0)
        dilution = num(row.get("fundamentals_fdv_to_market_cap"))
        supply_component = 10 * clipped(2 - dilution, 0, 1)
        # Recovery gets a small weight; EMA unavailability must NOT be
        # interpreted as bearish fundamentals.
        technical_component = 5 if row.get("technical_status") == "EMA CONFIRMED" else 0
        volume_daily = num(row.get("volume_daily_accel"))
        accumulation_component = 5 * clipped((volume_daily or 0) / 2, 0, 1)
        score = sum((valuation_component, fundamentals_component,
                     dislocation_component, liquidity_component,
                     supply_component, technical_component,
                     accumulation_component))
        r["undervaluation_score"] = round(score, 2)
        r["undervaluation_classification"] = (
            "HIGH RESEARCH PRIORITY" if score >= 75 else
            "POTENTIAL DISCOUNT" if score >= 60 else
            "MIXED VALUE SIGNALS")
        r["undervaluation_confidence"] = "PROVISIONAL"
        r["undervaluation_reasons"] = (
            f"Sector-peer market cap / 365d tokenholder revenue rank: "
            f"{cheaper_rank:.1%}; {len(group)} peers. "
            "Research score, not fair value or a buy recommendation. "
            "Unlock schedules, order books, audited token claims and true active users not verified.")
        results.append(r)
    return results


def run(reports):
    reports = Path(reports)
    file = reports / "breakout_radar.json"
    source = json.loads(file.read_text())
    if not isinstance(source, list):
        raise ValueError("Radar report must be a list")
    assessed = evaluate(source)
    fields = ("undervaluation_score", "undervaluation_classification",
              "undervaluation_confidence", "undervaluation_price_context",
              "undervaluation_peer_count", "undervaluation_sector", "undervaluation_reasons")
    # Separate output plus selected supplemental columns on existing radar.
    compact = [{"id": r.get("id"), "symbol": r.get("symbol"),
                "breakout_score": r.get("breakout_score"),
                **{k: r.get(k) for k in fields}} for r in assessed]
    compact.sort(key=lambda r: (r["undervaluation_score"] is None,
                                -(r["undervaluation_score"] or 0), str(r.get("symbol"))))
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "source": "Existing production radar and observational fundamentals only",
              "scoring_status": "PROVISIONAL RESEARCH; NOT A FAIR-VALUE ESTIMATE",
              "unrated": sum(r["undervaluation_score"] is None for r in compact),
              "rated": sum(r["undervaluation_score"] is not None for r in compact),
              "assets": compact}
    (reports / "undervaluation_radar.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    file.write_text(json.dumps(assessed, allow_nan=False) + "\n")
    csvpath = reports / "breakout_radar.csv"
    with csvpath.open(newline="") as handle:
        reader = csv.DictReader(handle)
        csvrows = list(reader)
        oldfields = list(reader.fieldnames)
    if len(csvrows) != len(assessed):
        raise ValueError("CSV/JSON row mismatch: no output written")
    lookup = {str(r.get("id")): r for r in assessed}
    if len(lookup) != len(assessed):
        raise ValueError("Duplicate asset IDs: refusing CSV mapping")
    for row in csvrows:
        match = lookup.get(str(row.get("id")))
        if not match:
            raise ValueError("CSV asset not in JSON: refusing output")
        for field in fields:
            value = match.get(field)
            row[field] = "" if value is None else value
    for field in fields:
        if field not in oldfields:
            oldfields.append(field)
    with csvpath.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=oldfields)
        writer.writeheader()
        writer.writerows(csvrows)
    print(f"Undervaluation research radar: {report['rated']} rated, {report['unrated']} unrated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args()
    run(args.reports_dir)
