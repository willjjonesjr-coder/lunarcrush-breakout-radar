"""Separate daily radar universe turnover from actual same-asset data degradation.

Uses published CSVs only; does not change scores, alerts, selection or API use.
"""
import csv
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPORTS = Path("reports")
STATUS = ("COMPLETE", "PARTIAL HISTORY", "INSUFFICIENT DATA")

def load(path):
    with path.open(newline="") as f:
        data = list(csv.DictReader(f))
    ids = [str(r.get("id","")) for r in data]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("Missing or duplicate coin IDs: cannot audit cohort")
    return {str(r["id"]):r for r in data}

def compare(before, after):
    overlap = set(before) & set(after)
    departed = set(before) - set(after)
    entered = set(after) - set(before)
    changed = []
    for cid in sorted(overlap, key=int):
        a, b = before[cid], after[cid]
        if a.get("data_status") != b.get("data_status"):
            changed.append({"coin_id":cid,"symbol":b.get("symbol"),
                "prior_status":a.get("data_status"),"current_status":b.get("data_status"),
                "prior_missing_fields":a.get("history_missing_fields"),
                "current_missing_fields":b.get("history_missing_fields")})
    return {"before_count":len(before),"after_count":len(after),
        "overlap":len(overlap),"exited":len(departed),"entered":len(entered),
        "turnover_pct_of_current":round(100 * len(entered)/len(after),2) if after else None,
        "prior_status_counts":dict(Counter(r.get("data_status") for r in before.values())),
        "current_status_counts":dict(Counter(r.get("data_status") for r in after.values())),
        "exited_status_counts":dict(Counter(before[x].get("data_status") for x in departed)),
        "entered_status_counts":dict(Counter(after[x].get("data_status") for x in entered)),
        "shared_prior_status_counts":dict(Counter(before[x].get("data_status") for x in overlap)),
        "shared_current_status_counts":dict(Counter(after[x].get("data_status") for x in overlap)),
        "same_asset_status_changes":changed,
        "same_asset_complete_to_incomplete":sum(before[x].get("data_status")=="COMPLETE" and after[x].get("data_status")!="COMPLETE" for x in overlap),
        "same_asset_incomplete_to_complete":sum(before[x].get("data_status")!="COMPLETE" and after[x].get("data_status")=="COMPLETE" for x in overlap),
        "new_assets": [{"coin_id":x,"symbol":after[x].get("symbol"),"data_status":after[x].get("data_status")} for x in sorted(entered,key=int)],
        "exited_assets": [{"coin_id":x,"symbol":before[x].get("symbol"),"data_status":before[x].get("data_status")} for x in sorted(departed,key=int)]}

def run(reports=REPORTS, today=None):
    today=today or datetime.now(timezone.utc).date()
    current=reports/"breakout_radar.csv"
    previous=reports/"archive"/f"breakout_radar_{today - timedelta(days=1):%Y-%m-%d}.csv"
    output=reports/"radar_cohort_quality_latest.json"
    if not previous.exists():
        result={"as_of_utc":today.isoformat(),"status":"NO PRIOR DAILY ARCHIVE",
                "prior_path":str(previous),"note":"No comparisons inferred from missing prior archive"}
    else:
        result={"as_of_utc":today.isoformat(),"status":"AVAILABLE","prior_path":str(previous),
                **compare(load(previous),load(current)),
                "note":"A change in cohort composition is not evidence of corrupted histories. Missing provider fields remain genuine coverage constraints."}
    output.write_text(json.dumps(result,indent=2)+"\n")
    print("Radar cohort quality:",result["status"],"turnover",result.get("entered"),
          "same asset regressions",result.get("same_asset_complete_to_incomplete"))
    return result

if __name__=="__main__":run()
