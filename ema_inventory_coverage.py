"""Report verified EMA inventory independent of changing 300-asset radar selection.

Read-only observational diagnostics. Never changes production scoring or alerts.
"""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from phase2_safeguards import technical_confirmation

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"


def generate(as_of=None):
    today = as_of or datetime.now(timezone.utc).date()
    freshness = json.loads((REPORTS / "ema_freshness_audit.json").read_text())
    with (REPORTS / "breakout_radar.csv").open(newline="") as f:
        radar = {str(r.get("id")): r for r in csv.DictReader(f)}
    assets = []
    for entry in freshness["assets"]:
        cid = str(entry["coin_id"])
        selected = cid in radar
        fresh = bool(entry["eligible"])
        # For off-universe assets evaluate technicals using approved coin-ID
        # file only. No LunarCrush history request, score, or alert is created.
        technical = (technical_confirmation(ROOT / "data_price" / (cid + ".csv"), today)
                     if fresh and not selected else None)
        assets.append({
            "coin_id": cid, "exchange": entry["exchange"], "pair": entry["pair"],
            "selected_in_300": selected, "fresh_300_bar_history": fresh,
            "last_completed_candle": entry["latest_candle"],
            "blocker": entry["blocker"],
            "technical_status": (radar[cid].get("technical_status") if selected
                                 else technical["technical_status"] if technical else "NOT EVALUATED"),
            "off_universe_technical": technical,
        })
    inventory_ids = {x["coin_id"] for x in assets}
    mapped_selection = sum(cid in radar for cid in inventory_ids)
    report = {
        "as_of": today.isoformat(),
        "verified_inventory_records": len(assets),
        "fresh_eligible_inventory": sum(x["fresh_300_bar_history"] for x in assets),
        "verified_in_current_300": mapped_selection,
        "ema_evaluable_in_current_300": sum(
            x["selected_in_300"] and x["technical_status"] in ("EMA CONFIRMED", "EMA NOT CONFIRMED")
            for x in assets),
        "off_universe_fresh_eligible": sum(
            x["fresh_300_bar_history"] and not x["selected_in_300"] for x in assets),
        "off_universe_technical_confirmed": sum(
            not x["selected_in_300"] and x["technical_status"] == "EMA CONFIRMED" for x in assets),
        "alert_policy": "Report only. Off-universe technical results never qualify for alerts or rankings.",
        "assets": assets,
    }
    return report


if __name__ == "__main__":
    result = generate()
    (REPORTS / "ema_inventory_coverage_latest.json").write_text(json.dumps(result, indent=2) + "\n")
    print("EMA inventory:", result["verified_inventory_records"],
          "fresh:", result["fresh_eligible_inventory"],
          "in current universe:", result["ema_evaluable_in_current_300"],
          "off universe:", result["off_universe_fresh_eligible"])
