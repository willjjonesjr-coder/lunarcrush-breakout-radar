"""Produce a review queue for staged EMA histories; never auto-approve identities."""
import csv
import json
from collections import Counter
from pathlib import Path

STAGED = Path("artifact-stage/review_results.csv")
RECONCILED = Path("artifact-identity/ema_identity_reconciliation.csv")
OUT = Path("reports/ema_staged_identity_review.csv")
FIELDS = ["coin_id","symbol","name","exchange","pair","coingecko_id",
          "identity_status","staging_status","decision","required_evidence"]

def review(stage, identities):
    by_id = {str(x["coin_id"]): x for x in identities}
    rows = []
    for item in stage:
        if item.get("status") != "STAGED":
            continue
        cid = str(item["coin_id"])
        match = by_id.get(cid)
        identity = match.get("identity_status","") if match else ""
        decision = ("REVIEW UNIQUE CANONICAL CANDIDATE"
                    if identity == "UNIQUE EXACT CANDIDATE — NOT VERIFIED"
                    else "MANUAL DISAMBIGUATION REQUIRED")
        rows.append({"coin_id":cid,"symbol":item.get("symbol",""),
                     "name":item.get("name",""),"exchange":item.get("exchange",""),
                     "pair":item.get("pair",""),
                     "coingecko_id":match.get("coingecko_id","") if match else "",
                     "identity_status":identity,"staging_status":item["status"],
                     "decision":decision,
                     "required_evidence":"CoinGecko canonical ID; LunarCrush ID; official contract/network (or native chain); independently verified exchange asset listing"})
    return rows

def main():
    with STAGED.open(newline="") as f: stage=list(csv.DictReader(f))
    with RECONCILED.open(newline="") as f: identities=list(csv.DictReader(f))
    rows=review(stage,identities)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader();writer.writerows(rows)
    summary={"staged_reviewed":len(rows),"decisions":dict(Counter(x["decision"] for x in rows)),
             "approved_for_import":0,
             "policy":"No symbol-only auto-approvals; manual documentary evidence required before importing."}
    OUT.with_suffix(".json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary))

if __name__=="__main__":main()
