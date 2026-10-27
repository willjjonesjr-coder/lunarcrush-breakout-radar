"""Read-only diagnosis of historical coverage failures; never invent missing bars."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def triage(rows):
    problems = []
    for row in rows:
        if row.get("history_selection") != "ANALYZED":
            continue
        status = row.get("data_status", "UNKNOWN")
        if status == "COMPLETE":
            continue
        try:
            missing = json.loads(row.get("history_missing_fields") or "{}")
        except (ValueError, TypeError):
            missing = {"invalid_missing_fields": 1}
        missing = {str(k): int(v) for k, v in missing.items() if str(v).isdigit() and int(v) > 0}
        priority = ("FETCH ERROR" if row.get("history_error") else
                    "MISSING DAILY BARS" if missing.get("close", 0) else
                    "PROVIDER FIELD GAPS" if missing else "MISSING SCORE FEATURES")
        problems.append({
            "id": row.get("id"), "symbol": row.get("symbol"), "name": row.get("name"),
            "data_status": status, "priority": priority,
            "history_error": row.get("history_error") or "",
            "missing_fields": missing,
            "missing_features": row.get("missing_features") or "",
            "expected_complete_day": row.get("expected_complete_day") or "",
            "latest_price_day": row.get("latest_price_day") or "",
        })
    counts = Counter(p["priority"] for p in problems)
    fields = Counter(k for p in problems for k in p["missing_fields"])
    return {
        "incomplete_candidates": len(problems),
        "issue_categories": dict(counts),
        "affected_assets_by_field": dict(fields.most_common()),
        "candidates": sorted(problems, key=lambda p: (
            {"FETCH ERROR": 0, "MISSING DAILY BARS": 1,
             "PROVIDER FIELD GAPS": 2, "MISSING SCORE FEATURES": 3}.get(p["priority"], 4),
            p["symbol"] or "", p["id"] or "")),
        "safety": "Diagnostic only; do not fill missing provider fields with zero, interpolate, or treat historical revisions as point-in-time data."
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default="reports/radar_candidates.csv")
    parser.add_argument("--output", default="reports/history_gap_triage.json")
    args = parser.parse_args()
    with open(args.candidates, newline="") as f:
        report = triage(list(csv.DictReader(f)))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print("History triage:", report["issue_categories"], report["affected_assets_by_field"])


if __name__ == "__main__":
    main()
