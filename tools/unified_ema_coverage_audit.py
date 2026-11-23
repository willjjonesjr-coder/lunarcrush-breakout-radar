#!/usr/bin/env python3
"""Read-only 300-candidate production/provisional EMA coverage audit.

Optional research inputs must be supplied from GitHub Actions artifacts. Missing
artifacts are reported as UNKNOWN, never construed as identity failures.
No imports to production inventories, scores, or notification paths occur.
"""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIELDS = (
    "coin_id", "symbol", "name", "breakout_score", "production_technical_status",
    "production_history_source", "production_ema_evaluable", "identity_status",
    "identity_evidence", "price_corroboration_status", "provisional_ema_status",
    "provisional_bars", "primary_blocker", "secondary_blockers", "research_ready",
    "artifact_sources", "review_action",
)
PASS_PRICE = {"PRICE_CORROBORATED"}
CONFLICT = {"IDENTITY_CONFLICT", "CONFLICT", "PRICE_MISMATCH", "AMBIGUOUS",
            "REJECTED", "INVALID_EXCHANGE_PRICE"}
INSUFFICIENT = {"INSUFFICIENT_HISTORY", "INSUFFICIENT_BARS", "HISTORY UNAVAILABLE",
                "INSUFFICIENT_ALIGNED_DATA", "NO_HISTORY", "STALE_HISTORY"}


def rows(path):
    if not path or not Path(path).is_file():
        return []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def json_data(path):
    if not path or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def key(row):
    return str(row.get("coin_id") or row.get("id") or "").strip()


def valid_match(production, evidence):
    """Do not merge different tokens that happen to share an ID in stale artifacts."""
    for field in ("symbol", "name"):
        a, b = str(production.get(field) or "").strip(), str(evidence.get(field) or "").strip()
        if a and b and a.casefold() != b.casefold():
            return False
    return True


def index(items):
    out, dup = {}, set()
    for item in items:
        cid = key(item)
        if not cid:
            continue
        if cid in out:
            dup.add(cid)
        else:
            out[cid] = item
    for cid in dup:
        out.pop(cid, None)
    return out, dup


def make(production, identity=(), price=(), provisional=(), history=(), supplied=None):
    supplied = supplied or {}
    selected = [x for x in production if str(x.get("history_selection", "")).upper() == "ANALYZED"]
    selected_ids = [key(x) for x in selected]
    if not selected or any(not x for x in selected_ids) or len(set(selected_ids)) != len(selected):
        raise ValueError("Need nonempty, uniquely keyed ANALYZED production candidates")
    maps = {}
    for label, records in (("identity", identity), ("price", price),
                           ("provisional", provisional), ("history", history)):
        maps[label] = index(records)
    output = []
    for prod in selected:
        cid = key(prod)
        evidence = {}
        discrepancies = []
        sources = []
        for label, (lookup, duplicates) in maps.items():
            if cid in duplicates:
                discrepancies.append(label + ":duplicate_coin_id")
                continue
            if cid not in lookup:
                continue
            row = lookup[cid]
            if not valid_match(prod, row):
                discrepancies.append(label + ":name_or_symbol_conflict")
                continue
            evidence[label] = row
            sources.append(label)
        technical = str(prod.get("technical_status") or "").strip()
        evaluable = bool(str(prod.get("ema50") or "").strip() and
                         str(prod.get("ema100") or "").strip() and
                         str(prod.get("ema200") or "").strip())
        identity_row = evidence.get("identity", {})
        price_row = evidence.get("price", {})
        prov_row = evidence.get("provisional", {})
        history_row = evidence.get("history", {})
        identity_state = str(identity_row.get("final_decision") or
                             identity_row.get("identity_state") or
                             identity_row.get("identity_status") or
                             identity_row.get("status") or "")
        price_state = str(price_row.get("corroboration_status") or
                          price_row.get("identity_confidence") or
                          price_row.get("status") or "")
        provisional_state = str(prov_row.get("provisional_technical_status") or
                                prov_row.get("ema_status") or
                                prov_row.get("status") or "")
        bars = str(prov_row.get("history_bars") or prov_row.get("bars") or
                   history_row.get("candles_max") or history_row.get("bars_available") or "")
        blockers = []
        if discrepancies:
            blockers.append("EVIDENCE_CONFLICT")
        if identity_state.upper() in CONFLICT or price_state.upper() in CONFLICT:
            blockers.append("IDENTITY_OR_PRICE_CONFLICT")
        if price_state.upper() in PASS_PRICE and not provisional_state.upper().startswith("PROVISIONAL EMA"):
            blockers.append("PRICE_CORROBORATED_EMA_NOT_READY")
        if (provisional_state.upper().startswith("PROVISIONAL EMA")
                or (price_state.upper() in PASS_PRICE and
                    str(prov_row.get("ema50") or price_row.get("ema50") or "").strip())):
            blockers.append("RESEARCH_TO_PRODUCTION_HANDOFF")
        if (provisional_state.upper() in INSUFFICIENT or
                price_state.upper() in INSUFFICIENT or
                str(history_row.get("history_status") or "").upper() in INSUFFICIENT):
            blockers.append("HISTORY_INSUFFICIENT_OR_STALE")
        if identity_state.upper() in {"PENDING", "REVIEW REQUIRED", "UNVERIFIED", "AMBIGUOUS"}:
            blockers.append("IDENTITY_REVIEW")
        if not sources:
            blockers.append("NO_MATCHING_RESEARCH_ARTIFACT")
        if not evaluable and not blockers:
            blockers.append("UNCLASSIFIED_MISSING_EMA")
        primary = "PRODUCTION_EMA_AVAILABLE" if evaluable else blockers[0]
        if evaluable and blockers:
            # Evidence issues still matter to research, but cannot override production data.
            secondary = blockers
        else:
            secondary = blockers[1:]
        research_ready = (not evaluable and
                          "RESEARCH_TO_PRODUCTION_HANDOFF" in blockers and
                          not any(x in blockers for x in ("EVIDENCE_CONFLICT",
                                  "IDENTITY_OR_PRICE_CONFLICT", "HISTORY_INSUFFICIENT_OR_STALE")))
        if evaluable:
            action = "NONE"
        elif research_ready:
            action = "INCLUDE_IN_LABELED_PROVISIONAL_RESEARCH_ONLY"
        elif primary in ("EVIDENCE_CONFLICT", "IDENTITY_OR_PRICE_CONFLICT"):
            action = "REVIEW_CONFLICT"
        elif primary in ("HISTORY_INSUFFICIENT_OR_STALE", "PRICE_CORROBORATED_EMA_NOT_READY"):
            action = "FETCH_OR_REPAIR_COMPLETED_DAILY_HISTORY"
        else:
            action = "COLLECT_MISSING_RESEARCH_EVIDENCE"
        output.append(dict(
            coin_id=cid, symbol=prod.get("symbol", ""), name=prod.get("name", ""),
            breakout_score=prod.get("breakout_score", ""),
            production_technical_status=technical,
            production_history_source=prod.get("ema_history_source", ""),
            production_ema_evaluable="YES" if evaluable else "NO",
            identity_status=identity_state or "UNKNOWN",
            identity_evidence=identity_row.get("evidence_gaps") or identity_row.get("reason") or "",
            price_corroboration_status=price_state or "UNKNOWN",
            provisional_ema_status=provisional_state or "UNKNOWN",
            provisional_bars=bars, primary_blocker=primary,
            secondary_blockers=";".join(secondary + discrepancies),
            research_ready="YES" if research_ready else "NO",
            artifact_sources=";".join(sources),
            review_action=action))
    output.sort(key=lambda x: (-float(x["breakout_score"] or 0), x["coin_id"]))
    counts = Counter(x["primary_blocker"] for x in output)
    return output, {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_candidates": len(output),
        "production_ema_evaluable": sum(x["production_ema_evaluable"] == "YES" for x in output),
        "production_ema_missing": sum(x["production_ema_evaluable"] == "NO" for x in output),
        "provisional_research_ready": sum(x["research_ready"] == "YES" for x in output),
        "primary_blocker_counts": dict(sorted(counts.items())),
        "artifact_status": {k: ("SUPPLIED" if supplied.get(k) else "NOT_SUPPLIED")
                            for k in ("identity", "price", "provisional", "history")},
        "policy": "Coverage inventory only. Provisional evidence never authorizes alerts or production identity imports.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--production", default="reports/breakout_radar.csv")
    p.add_argument("--identity", help="EMA master identity CSV artifact")
    p.add_argument("--price", help="47-CEX research summary or price corroboration CSV artifact")
    p.add_argument("--provisional", help="Provisional EMA report.json or research CSV artifact")
    p.add_argument("--history", help="Expanded CEX identity readiness CSV artifact")
    p.add_argument("--output", default="reports/unified_ema_coverage")
    args = p.parse_args()
    production = rows(args.production)
    if not production:
        p.error("Production CSV not found or empty")
    optional = {k: getattr(args, k) for k in ("identity", "price", "provisional", "history")}
    for kind, source in optional.items():
        if source and not Path(source).is_file():
            p.error(kind + " input does not exist: " + source)
    identity = rows(args.identity)
    price = rows(args.price)
    history = rows(args.history)
    provisional_data = json_data(args.provisional) if args.provisional and args.provisional.endswith(".json") else None
    provisional = (provisional_data.get("assets", []) if isinstance(provisional_data, dict)
                   else rows(args.provisional))
    result, summary = make(production, identity, price, provisional, history,
                           supplied={k: bool(v) for k, v in optional.items()})
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "coverage.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(result)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
