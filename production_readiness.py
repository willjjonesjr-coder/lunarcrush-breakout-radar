"""Read-only production readiness audit. No API calls and no trading signals."""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path


def audit(data_dir, reports_dir, as_of=None):
    today = date.fromisoformat(as_of) if as_of else date.today()
    snapshots = data_dir / "volume_snapshot_history.json"
    history = json.loads(snapshots.read_text()) if snapshots.exists() else {}
    required = [(today - timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
    present = [d for d in required if isinstance(history.get(d), dict) and history[d]]
    missing = [d for d in required if d not in present]
    volume_file = reports_dir / "volume_surge_latest.json"
    volume = json.loads(volume_file.read_text()) if volume_file.exists() else {}
    segments = volume.get("segments", [])
    ready = [s["segment"] for s in segments if s.get("status") == "READY"]
    blocked = {s.get("segment", "unknown"): s.get("status", "UNKNOWN") for s in segments if s.get("status") != "READY"}
    coverage_file = reports_dir / "radar_coverage.json"
    coverage = json.loads(coverage_file.read_text()) if coverage_file.exists() else {}
    status = coverage.get("data_status_counts", {})
    total = coverage.get("history_candidates", 0)
    complete = status.get("COMPLETE", 0)
    report = {
        "as_of": today.isoformat(),
        "baseline": {
            "required_dates": required, "present_dates": present, "missing_dates": missing,
            "ready": not missing, "ready_segments": ready, "blocked_segments": blocked,
            "note": "Do not synthesize missing snapshots from 24h rolling volumes or historical coin candles."
        },
        "history": {
            "attempted": total, "complete": complete,
            "partial": status.get("PARTIAL HISTORY", 0),
            "insufficient": status.get("INSUFFICIENT DATA", 0),
            "complete_pct": round(100 * complete / total, 1) if total else None,
            "missing_fields": coverage.get("history_missing_field_counts", {}),
        },
        "next_actions": [
            "Collect one UTC-dated snapshot daily until seven preceding dates are present.",
            "Audit missing spam, sentiment, and social-history fields before increasing the API budget.",
            "Validate coin IDs and reported-volume provenance before enabling automated alerts.",
            "Do not interpret a successful workflow as a confirmed breakout."
        ]
    }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()
    report = audit(Path(args.data_dir), Path(args.reports_dir), args.as_of)
    output = Path(args.reports_dir) / "production_readiness.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
