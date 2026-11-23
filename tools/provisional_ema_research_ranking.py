#!/usr/bin/env python3
"""Rank provisional research candidates without changing any production behavior.

Only audited research_ready=YES candidates are eligible for this separate list.
Historical evidence is labeled stale unless its source explicitly matches the
production report's completed UTC day. No notifications or symbol-map writes.
"""
import argparse
import csv
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

FIELDS = (
    "research_rank", "coin_id", "symbol", "name", "breakout_score",
    "research_label", "identity_status", "price_corroboration_status",
    "provisional_ema_status", "ema50", "ema100", "ema200",
    "ema_history_bars", "ema_evidence_source", "ema_evidence_day",
    "production_expected_day", "evidence_freshness", "research_priority",
    "current_selection_status", "current_expected_day", "current_ema_evaluable",
    "caution_flags", "production_eligible", "alert_eligible",
)


def csv_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def indexed(rows):
    result, duplicates = {}, set()
    for r in rows:
        cid = str(r.get("coin_id") or r.get("id") or "").strip()
        if not cid:
            continue
        if cid in result:
            duplicates.add(cid)
        else:
            result[cid] = r
    for cid in duplicates:
        result.pop(cid, None)
    return result, duplicates


def consistent(candidate, other):
    for field in ("name", "symbol"):
        a = str(candidate.get(field) or "").strip().casefold()
        b = str(other.get(field) or "").strip().casefold()
        if a and b and a != b:
            return False
    return True


def day(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return ""


def values(row, prefix=""):
    result = []
    for n in (50, 100, 200):
        raw = row.get(prefix + "ema" + str(n))
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        result.append(number)
    return result


def build(coverage, production, price=(), provisional=(), provisional_report=None,
          current_production=None):
    prod, prod_duplicate = indexed(production)
    current, current_duplicates = indexed(current_production or [])
    prices, price_duplicate = indexed(price)
    prov, prov_duplicate = indexed(provisional)
    report = provisional_report or {}
    report_as_of = day(report.get("as_of"))
    report_day = day(report.get("required_completed_day"))
    ready = [r for r in coverage if str(r.get("research_ready", "")).upper() == "YES"]
    seen = set()
    output = []
    for row in ready:
        cid = str(row.get("coin_id") or "").strip()
        if not cid or cid in seen:
            raise ValueError("Duplicate or missing candidate ID in coverage audit")
        seen.add(cid)
        if cid in prod_duplicate or cid not in prod or not consistent(row, prod[cid]):
            raise ValueError("Production ID missing, duplicated, or mismatched: " + cid)
        source_prod = prod[cid]
        if str(source_prod.get("history_selection") or "") != "ANALYZED":
            raise ValueError("Unselected production candidate: " + cid)
        if any(str(source_prod.get("ema" + str(n)) or "").strip() for n in (50,100,200)):
            raise ValueError("Research candidate has production EMA fields: " + cid)
        expected = day(source_prod.get("expected_complete_day") or source_prod.get("latest_price_day"))
        if not expected:
            raise ValueError("Missing production reference day: " + cid)
        flags = []
        current_row = current.get(cid)
        if cid in current_duplicates:
            current_status = "DUPLICATE_CURRENT_ID"
            flags.append("CURRENT_ID_CONFLICT")
        elif current_row is None:
            current_status = "NOT_IN_CURRENT_REPORT" if current_production is not None else "NOT_CHECKED"
            if current_production is not None:
                flags.append("NOT_IN_CURRENT_REPORT")
        elif not consistent(row, current_row):
            current_status = "CURRENT_NAME_SYMBOL_CONFLICT"
            flags.append("CURRENT_NAME_SYMBOL_CONFLICT")
        elif current_row.get("history_selection") != "ANALYZED":
            current_status = "NOT_IN_CURRENT_300"
            flags.append("NOT_IN_CURRENT_300")
        else:
            current_status = "CURRENT_ANALYZED"
        current_day = day(current_row.get("expected_complete_day") or
                          current_row.get("latest_price_day")) if current_row else ""
        current_ema = bool(current_row and all(
            str(current_row.get("ema" + str(n)) or "").strip() for n in (50, 100, 200)))
        if current_ema:
            flags.append("CURRENT_PRODUCTION_EMA_AVAILABLE")
        if current_row and current_day and current_day != expected:
            flags.append("CURRENT_REPORT_DAY_DIFFERS")
        evidence = []
        if cid in price_duplicate or cid in prov_duplicate:
            flags.append("DUPLICATE_SOURCE_ID")
        else:
            for origin, indexed_rows in (("provisional", prov), ("price", prices)):
                evidence_row = indexed_rows.get(cid)
                if evidence_row:
                    if consistent(row, evidence_row):
                        evidence.append((origin, evidence_row))
                    else:
                        flags.append(origin.upper() + "_IDENTITY_CONFLICT")
        if str(row.get("primary_blocker")) != "RESEARCH_TO_PRODUCTION_HANDOFF":
            flags.append("AUDIT_BLOCKER_MISMATCH")
        secondary = str(row.get("secondary_blockers") or "")
        if any(x in secondary for x in ("CONFLICT", "IDENTITY_REVIEW", "HISTORY_INSUFFICIENT")):
            flags.append("AUDIT_CONFLICT_OR_REVIEW")
        usable = []
        for origin, e in evidence:
            state = str(e.get("provisional_technical_status") or e.get("ema_status") or "")
            vals = values(e, "provisional_" if origin == "provisional" else "")
            if state.startswith("PROVISIONAL EMA") and vals:
                usable.append((origin, e, state, vals))
        # Prefer a dated provisional record only if it has complete EMA values.
        usable.sort(key=lambda t: (t[0] != "provisional", t[0]))
        chosen = usable[0] if usable else None
        if chosen:
            origin, evidence_row, state, ema = chosen
            bars = str(evidence_row.get("history_bars") or evidence_row.get("bars") or
                       row.get("provisional_bars") or "")
            evidence_day = day(evidence_row.get("history_last_day") or
                               evidence_row.get("latest_day"))
            if origin == "provisional":
                # The report's global freshness must be valid as well as per-asset day.
                fresh = (bool(evidence_day) and evidence_day == expected
                         and report_day == expected
                         and report_as_of == (date.fromisoformat(expected) + timedelta(days=1)).isoformat())
            else:
                fresh = evidence_day == expected and bool(evidence_day)
            if origin == "price" and not evidence_day:
                flags.append("PRICE_EMA_DATE_NOT_VERIFIED")
            if not fresh:
                flags.append("STALE_OR_UNVERIFIED_EMA_EVIDENCE")
            if bars:
                try:
                    if int(bars) < 300:
                        flags.append("INSUFFICIENT_EMA_BARS")
                except ValueError:
                    flags.append("EMA_BAR_COUNT_UNKNOWN")
            else:
                flags.append("EMA_BAR_COUNT_UNKNOWN")
        else:
            origin, state, ema, bars, evidence_day, fresh = "", "NOT EVALUABLE", None, "", "", False
            flags.append("EMA_VALUES_NOT_AVAILABLE")
        identity = str(row.get("identity_status") or "UNKNOWN")
        if identity.upper() != "VERIFIED":
            flags.append("IDENTITY_PROVISIONAL_USER_REVIEW")
        if str(row.get("price_corroboration_status") or "").upper() not in ("PRICE_CORROBORATED",):
            flags.append("PRICE_CORROBORATION_NOT_CONFIRMED")
        if str(source_prod.get("liquidity_label") or "").startswith("BELOW"):
            flags.append("LOW_LIQUIDITY_REFERENCE")
        try:
            score = float(row.get("breakout_score") or source_prod.get("breakout_score") or 0)
        except ValueError:
            score = 0.
        if not math.isfinite(score):
            raise ValueError("Non-finite breakout score: " + cid)
        freshness = "FRESH" if fresh else ("STALE_OR_UNVERIFIED" if chosen else "MISSING_VALUES")
        priority = ("REVIEW_FRESH_PROVISIONAL" if fresh and not
                    any("CONFLICT" in x or "INSUFFICIENT" in x for x in flags)
                    else "REFRESH_OR_RECONCILE_EVIDENCE")
        output.append(dict(
            research_rank="", coin_id=cid, symbol=row.get("symbol") or "",
            name=row.get("name") or "", breakout_score=round(score, 4),
            research_label="PROVISIONAL / RESEARCH ONLY", identity_status=identity,
            price_corroboration_status=row.get("price_corroboration_status") or "UNKNOWN",
            provisional_ema_status=state,
            ema50=ema[0] if ema else "", ema100=ema[1] if ema else "",
            ema200=ema[2] if ema else "", ema_history_bars=bars,
            ema_evidence_source=origin or "NONE", ema_evidence_day=evidence_day,
            production_expected_day=expected, evidence_freshness=freshness,
            research_priority=priority, current_selection_status=current_status,
            current_expected_day=current_day,
            current_ema_evaluable="YES" if current_ema else "NO",
            caution_flags=";".join(dict.fromkeys(flags)),
            production_eligible="NO", alert_eligible="NO"))
    output.sort(key=lambda r: (-float(r["breakout_score"]), r["coin_id"]))
    for position, item in enumerate(output, 1):
        item["research_rank"] = position
    return output, {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cohort_size": len(output),
        "fresh_ema": sum(x["evidence_freshness"] == "FRESH" for x in output),
        "stale_or_unverified_ema": sum(x["evidence_freshness"] == "STALE_OR_UNVERIFIED" for x in output),
        "missing_ema_values": sum(x["evidence_freshness"] == "MISSING_VALUES" for x in output),
        "priority_counts": dict(Counter(x["research_priority"] for x in output)),
        "current_selection_counts": dict(Counter(x["current_selection_status"] for x in output)),
        "snapshot_note": "EMA evidence freshness is relative to the original coverage snapshot, not today's market.",
        "production_promotions": 0,
        "alerts": 0,
        "policy": "Standalone provisional research only, no production promotion or notifications."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--production", default="reports/breakout_radar.csv",
                        help="Production CSV at the exact coverage audit commit")
    parser.add_argument("--current-production",
                        help="Optional latest production CSV for non-blocking status comparison")
    parser.add_argument("--price")
    parser.add_argument("--provisional")
    parser.add_argument("--output", default="reports/provisional_ema_research_ranking")
    args = parser.parse_args()
    report = {}
    provisional = []
    if args.provisional:
        report = json.loads(Path(args.provisional).read_text())
        if not isinstance(report, dict) or not isinstance(report.get("assets"), list):
            parser.error("Provisional input must be report.json with assets")
        provisional = report["assets"]
    output, summary = build(csv_rows(args.coverage), csv_rows(args.production),
                            csv_rows(args.price) if args.price else [], provisional, report,
                            current_production=csv_rows(args.current_production)
                            if args.current_production else None)
    target = Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    with (target / "ranking.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)
    (target / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
