"""Audit what prevents selloff candidates from receiving defensible valuation scores.

No new API requests, ranking eligibility, score, or alert changes.
"""
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from undervaluation_radar import num, financials_ok, peer_multiples, drawdown_status

REPORTS = Path("reports")
FIELDS = (
    ("verified_fundamentals_identity", lambda r: r.get("fundamentals_mapping") == "exact_name_and_symbol"),
    ("moderate_fundamentals_confidence", lambda r: r.get("fundamentals_confidence") == "MODERATE"),
    ("sector", lambda r: bool(r.get("fundamentals_sector"))),
    ("positive_holder_revenue_365d", lambda r: (num(r.get("fundamentals_holder_revenue_365d")) or 0) > 0),
    ("holder_revenue_multiple", lambda r: (num(r.get("fundamentals_market_cap_to_holder_revenue_365d")) or 0) > 0),
    ("fees_growth_30d", lambda r: num(r.get("fundamentals_fees_growth_30d")) is not None),
    ("revenue_growth_30d", lambda r: num(r.get("fundamentals_revenue_growth_30d")) is not None),
    ("holder_revenue_growth_30d", lambda r: num(r.get("fundamentals_holder_revenue_growth_30d")) is not None),
    ("dilution_ratio", lambda r: num(r.get("fundamentals_fdv_to_market_cap")) is not None),
    ("price_change_30d", lambda r: num(r.get("price_change_30d")) is not None),
)

def audit(rows):
    peer_groups = peer_multiples(rows)
    missing_counts = Counter()
    out = []
    for r in rows:
        missing = [name for name, ok in FIELDS if not ok(r)]
        sector = str(r.get("fundamentals_sector") or "")
        if sector not in peer_groups:
            missing.append("at_least_three_comparable_peers")
        missing_counts.update(missing)
        p30 = num(r.get("price_change_30d"))
        p7 = num(r.get("price_change_7d"))
        # Ordering is research triage, not a relative-value or buy signal.
        evidence = len(FIELDS) + 1 - len(missing)
        is_selloff = p30 is not None and p30 <= -.20
        out.append({
            "id": r.get("id"), "symbol": r.get("symbol"),
            "price_change_30d": p30, "price_change_7d": p7,
            "price_context": drawdown_status(r),
            "evidence_fields_present": evidence,
            "evidence_fields_required": len(FIELDS) + 1,
            "missing_evidence": missing,
            "sector": sector or None,
            "fundamentals_status": r.get("fundamentals_status"),
            "valuation_ready": financials_ok(r) and sector in peer_groups,
            "research_priority": "SELL-OFF EVIDENCE REVIEW" if is_selloff else "OTHER",
        })
    out.sort(key=lambda r: (
        r["research_priority"] != "SELL-OFF EVIDENCE REVIEW",
        -r["evidence_fields_present"],
        r["price_change_30d"] if r["price_change_30d"] is not None else 999,
        str(r["id"])))
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total": len(rows),
        "valuation_ready": sum(r["valuation_ready"] for r in out),
        "selloff_candidates": sum(r["research_priority"] == "SELL-OFF EVIDENCE REVIEW" for r in out),
        "missing_evidence_counts": dict(missing_counts.most_common()),
        "note": "Evidence triage only: a price decline does not establish undervaluation. No valuation score or alert is assigned.",
        "assets": out,
    }

def main():
    rows = json.loads((REPORTS / "breakout_radar.json").read_text())
    report = audit(rows)
    (REPORTS / "undervaluation_evidence_gaps.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    with (REPORTS / "undervaluation_evidence_gaps.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id","symbol","price_change_30d","price_change_7d","price_context","evidence_fields_present","evidence_fields_required","missing_evidence","sector","fundamentals_status","valuation_ready","research_priority"])
        writer.writeheader()
        for row in report["assets"]:
            writer.writerow({**row, "missing_evidence": "; ".join(row["missing_evidence"])})
    print(f"Valuation evidence gaps: {report['valuation_ready']}/{report['total']} ready; {report['selloff_candidates']} selloff reviews")

if __name__ == "__main__":
    main()
