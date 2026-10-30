"""Audit EMA freshness independently of social-history completeness.

Run after scanner and phase1_monitor, before publishing alerts.
No ticker inference or synthetic bars.
"""
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
PRICE = ROOT / "data_price"

def audit(as_of=None):
    today = as_of or datetime.now(timezone.utc).date()
    required = today - timedelta(days=1)
    inventory = REPORTS / "backfill_inventory.csv"
    mapping_file = ROOT / "config" / "symbol_map.json"
    mappings = json.loads(mapping_file.read_text()) if mapping_file.exists() else {}
    rows = list(csv.DictReader(inventory.open(newline=""))) if inventory.exists() else []
    records = []
    for row in rows:
        cid = str(row.get("coin_id", ""))
        mapping = mappings.get(cid, {})
        path = PRICE / (cid + ".csv")
        reason = None
        last = None
        if mapping.get("exchange") != row.get("exchange") or mapping.get("pair") != row.get("pair"):
            reason = "UNVERIFIED ID/PAIR"
        elif row.get("status") not in ("ok", "partial") or row.get("gaps_detected") not in ("0", ""):
            reason = "BACKFILL INVENTORY NOT VALID"
        elif not path.exists():
            reason = "PRICE FILE MISSING"
        else:
            try:
                with path.open(newline="") as f:
                    candles = list(csv.DictReader(f))
                if not candles or any(c.get("exchange") != row.get("exchange") or c.get("pair") != row.get("pair") for c in candles):
                    reason = "PRICE PROVENANCE MISMATCH"
                else:
                    days = sorted({date.fromisoformat(c["time"][:10]) for c in candles if c.get("time") and float(c.get("close") or 0) > 0 and date.fromisoformat(c["time"][:10]) < today})
                    last = days[-1].isoformat() if days else None
                    if len(days) < 300:
                        reason = "FEWER THAN 300 COMPLETED BARS"
                    elif days[-1] != required:
                        reason = "STALE LAST COMPLETED CANDLE"
                    elif any((b-a).days != 1 for a,b in zip(days[-300:], days[-299:])):
                        reason = "GAPS IN LAST 300 BARS"
            except (ValueError, OSError, KeyError):
                reason = "INVALID PRICE DATA"
        records.append({"coin_id": cid, "exchange": row.get("exchange"), "pair": row.get("pair"), "latest_candle": last, "eligible": reason is None, "blocker": reason})
    result = {"as_of_utc": today.isoformat(), "required_last_completed_candle": required.isoformat(), "inventory_assets": len(records), "eligible": sum(r["eligible"] for r in records), "blockers": dict(Counter(r["blocker"] for r in records if r["blocker"])), "assets": records}
    return result

if __name__ == "__main__":
    report = audit()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "ema_freshness_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print("EMA freshness audit:", report["eligible"], "/", report["inventory_assets"], "eligible; blockers:", report["blockers"])
