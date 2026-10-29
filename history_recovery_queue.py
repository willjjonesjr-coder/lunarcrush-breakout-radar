"""Conservative recovery priority queue: reports only; no extra API calls."""
import argparse
import csv
import json
from pathlib import Path


def queue(rows, limit=50):
    candidates = []
    for row in rows:
        if row.get("history_selection") != "ANALYZED" or row.get("data_status") == "COMPLETE":
            continue
        try:
            missing = json.loads(row.get("history_missing_fields") or "{}")
        except (ValueError, TypeError):
            missing = {}
        missing = {k: int(v) for k, v in missing.items() if str(v).isdigit() and int(v) > 0}
        # Prioritize high-ranking candidates with fewer gaps, but keep all in report.
        try:
            score = float(row.get("snapshot_score") or 0)
        except (ValueError, TypeError):
            score = 0.0
        gaps = sum(missing.values())
        reason = ("FETCH FAILURE" if row.get("history_error") else
                  "MISSING PRICE BARS" if missing.get("close") else
                  "MISSING PROVIDER FIELDS" if missing else "MISSING FEATURES")
        candidates.append({
            "id": str(row.get("id") or ""), "symbol": str(row.get("symbol") or ""),
            "name": str(row.get("name") or ""), "snapshot_score": round(score, 3),
            "gap_count": gaps, "reason": reason, "missing_fields": missing,
            "history_error": row.get("history_error") or "",
            "action": ("REVIEW FETCH FAILURE" if reason == "FETCH FAILURE" else
                       "VERIFY PROVIDER AVAILABILITY; NO IMPUTATION"),
        })
    candidates.sort(key=lambda r: (-r["snapshot_score"], r["gap_count"], r["id"]))
    return {
        "total_incomplete": len(candidates), "suggested_review_limit": limit,
        "review_first": candidates[:limit], "all_incomplete": candidates,
        "policy": "Do not request retries automatically. Review API budget, source history, coin ID and missing-field availability first."
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--candidates", default="reports/radar_candidates.csv")
    p.add_argument("--output", default="reports/history_recovery_queue.json")
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args()
    with open(args.candidates, newline="") as f:
        report = queue(list(csv.DictReader(f)), max(0, args.limit))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    print("Recovery queue:", report["total_incomplete"], "incomplete; review first", len(report["review_first"]))


if __name__ == "__main__":
    main()
