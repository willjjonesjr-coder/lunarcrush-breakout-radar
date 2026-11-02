"""Consolidated, traceable EMA identity audit. NEVER grants approval."""
import csv
import json
from pathlib import Path

STAGE=Path("artifact-stage/review_results.csv")
RECON=Path("artifact-reconciliation/ema_identity_reconciliation.csv")
EVIDENCE=Path("artifact-evidence/ema_identity_evidence_30.csv")
APPROVALS=Path("config/ema_identity_approvals.json")
OUT=Path("reports/ema_master_identity_audit.csv")
FIELDS=["coin_id","lunarcrush_symbol","lunarcrush_name","lunarcrush_network_raw",
"lunarcrush_contract_raw","coingecko_id","coingecko_symbol_raw","coingecko_name_raw",
"coingecko_platform_contracts_raw","project_network_raw","project_contract_raw",
"exchange","exchange_pair","exchange_asset_id_raw","exchange_network_raw",
"exchange_contract_raw","staging_status","identity_candidate_status",
"coingecko_listing_status","lunarcrush_canonical_comparison",
"project_coingecko_contract_comparison","project_coingecko_network_comparison",
"exchange_canonical_comparison","project_evidence_url","exchange_evidence_url",
"coingecko_evidence_url","reviewer","reviewed_at","approval_record_status",
"final_decision","evidence_gaps"]

def records(path):
    if not path.exists(): return []
    with path.open(newline="") as f: return list(csv.DictReader(f))

def compare(a,b):
    if not a or not b: return "UNKNOWN"
    return "MATCH" if a.strip().casefold()==b.strip().casefold() else "MISMATCH"

def make(stage,recon,evidence,approvals):
    re={str(x["coin_id"]):x for x in recon}
    ev={str(x["coin_id"]):x for x in evidence}
    out=[]
    for x in stage:
        cid=str(x["coin_id"]); a=re.get(cid,{}); e=ev.get(cid,{})
        p=approvals.get(cid,{})
        platforms={}
        for raw in (e.get("coin_platforms"),a.get("platform_contracts")):
            try:
                obj=json.loads(raw or "{}")
                if isinstance(obj,dict): platforms=obj;break
            except (ValueError,TypeError): pass
        pn=str(p.get("network",""))
        pc=str(p.get("contract_address",""))
        cg_contract=str(platforms.get(pn,"")) if pn else ""
        if isinstance(platforms.get(pn),dict):
            cg_contract=str(platforms[pn].get("contract_address",""))
        canonical=compare(x.get("symbol",""),a.get("symbol",""))
        # Comparing shared input symbol does not substantiate canonical identity.
        canonical="UNKNOWN" if canonical=="MATCH" else canonical
        project_contract=compare(pc,cg_contract)
        project_network="UNKNOWN"  # CoinGecko platform key may be an alias, not a normalized chain ID.
        exchange_identity="UNKNOWN"  # A ticker/pair listing alone never proves token contract identity.
        gaps=[]
        for label,val in [("project contract/native chain",pc or p.get("native_chain")),
                          ("official project evidence",p.get("project_evidence_url")),
                          ("independent exchange evidence",p.get("exchange_evidence_url")),
                          ("exchange asset identifier",p.get("exchange_asset_id")),
                          ("reviewer",p.get("reviewer"))]:
            if not val: gaps.append(label)
        status="PENDING"
        if any(v=="MISMATCH" for v in (canonical,project_contract,project_network,exchange_identity)):
            status="AMBIGUOUS"
        row=dict.fromkeys(FIELDS,"")
        row.update(coin_id=cid,lunarcrush_symbol=x.get("symbol",""),lunarcrush_name=x.get("name",""),
            lunarcrush_network_raw=p.get("lunarcrush_network",""),
            lunarcrush_contract_raw=p.get("lunarcrush_contract",""),
            coingecko_id=e.get("coingecko_id") or a.get("coingecko_id",""),
            coingecko_symbol_raw=a.get("coingecko_symbol",""),
            coingecko_name_raw=a.get("coingecko_name",""),
            coingecko_platform_contracts_raw=json.dumps(platforms,sort_keys=True),
            project_network_raw=pn,project_contract_raw=pc,
            exchange=x.get("exchange",""),exchange_pair=x.get("pair",""),
            exchange_asset_id_raw=p.get("exchange_asset_id",""),
            exchange_network_raw=p.get("exchange_network",""),
            exchange_contract_raw=p.get("exchange_contract",""),
            staging_status=x.get("status",""),identity_candidate_status=a.get("identity_status",""),
            coingecko_listing_status=e.get("coingecko_exchange_listing",""),
            lunarcrush_canonical_comparison=canonical,
            project_coingecko_contract_comparison=project_contract,
            project_coingecko_network_comparison=project_network,
            exchange_canonical_comparison=exchange_identity,
            project_evidence_url=p.get("project_evidence_url",""),
            exchange_evidence_url=p.get("exchange_evidence_url",""),
            coingecko_evidence_url=e.get("evidence_url",""),
            reviewer=p.get("reviewer",""),reviewed_at=p.get("reviewed_at",""),
            approval_record_status=p.get("status",""),
            final_decision=status,evidence_gaps="; ".join(gaps))
        out.append(row)
    return out

def main():
    approvals=json.loads(APPROVALS.read_text()) if APPROVALS.exists() else {}
    rows=make(records(STAGE),records(RECON),records(EVIDENCE),approvals)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
    summary={"rows":len(rows),"verified":0,"unknown_contracts":sum(x["project_coingecko_contract_comparison"]=="UNKNOWN" for x in rows),
             "policy":"Comparison UNKNOWN when evidence absent; all records pending substantive review; no production approval."}
    OUT.with_suffix(".json").write_text(json.dumps(summary,indent=2)+"\n")
    print(summary)

if __name__=="__main__":main()
