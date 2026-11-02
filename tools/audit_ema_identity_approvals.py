"""Fail-closed verification of proposed EMA asset identity approvals.

Never creates or modifies the production symbol map or backfill inventory.
Approval requires a reviewer-maintained record and independent evidence URLs.
"""
import csv
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"artifact-evidence/ema_identity_evidence_30.csv"
APPROVALS=ROOT/"config/ema_identity_approvals.json"
OUTPUT=ROOT/"reports/ema_identity_approval_audit.json"

def valid_url(value):
    u=urlparse(str(value or ""))
    return u.scheme=="https" and bool(u.netloc)

def evaluate(evidence, approvals):
    reference={str(r["coin_id"]):r for r in evidence}
    findings=[]
    for cid,record in approvals.items():
        problems=[]
        source=reference.get(str(cid))
        if source is None:
            problems.append("Not present in successful evidence batch")
        elif source.get("coingecko_exchange_listing")!="FOUND":
            problems.append("No matching exchange listing evidence")
        if record.get("status")!="approved":
            problems.append("Reviewer approval missing")
        for field in ("canonical_id","exchange","pair","reviewed_at","reviewer",
                      "project_evidence_url","exchange_evidence_url","identity_basis"):
            if not record.get(field):
                problems.append("Missing "+field)
        for field in ("project_evidence_url","exchange_evidence_url"):
            if not valid_url(record.get(field)):
                problems.append("Invalid "+field)
        if record.get("identity_basis")=="contract":
            for field in ("network","contract_address"):
                if not record.get(field):
                    problems.append("Missing "+field)
        elif record.get("identity_basis")=="native":
            if not record.get("native_chain"):
                problems.append("Missing native_chain")
        else:
            problems.append("identity_basis must be contract or native")
        if source:
            if record.get("canonical_id")!=source.get("coingecko_id"):
                problems.append("Canonical ID mismatch")
            if record.get("exchange")!=source.get("exchange") or record.get("pair")!=source.get("pair"):
                problems.append("Exchange pair mismatch")
        findings.append({"coin_id":str(cid),"status":"EVIDENCE REVIEW REQUIRED" if problems else "DOCUMENTARY GATE PASSED — HUMAN VALIDATION REQUIRED","blockers":problems})
    return {"candidates":len(reference),"submitted_approvals":len(approvals),
            "documentary_complete":sum(not r["blockers"] for r in findings),
            "production_imports":0,
            "policy":"Documentary completeness does not establish true identity. Manual verification required; never auto-import.",
            "assets":findings}

def main():
    with EVIDENCE.open(newline="") as f:
        evidence=list(csv.DictReader(f))
    approvals=json.loads(APPROVALS.read_text()) if APPROVALS.exists() else {}
    report=evaluate(evidence,approvals)
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="assets"}))

if __name__=="__main__": main()
