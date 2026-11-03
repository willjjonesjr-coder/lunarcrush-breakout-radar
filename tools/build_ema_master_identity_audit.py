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
"coingecko_platform_contracts_raw","coingecko_networks_raw","project_network_raw","project_contract_raw",
"exchange","exchange_pair","exchange_asset_id_raw","exchange_network_raw",
"exchange_contract_raw","staging_status","identity_candidate_status",
"coingecko_listing_status","lunarcrush_canonical_comparison",
"lunarcrush_coingecko_name_comparison","lunarcrush_coingecko_symbol_comparison","coingecko_id_cross_source_comparison",
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

def compare_contract(a, b, network):
    if not a or not b:
        return "UNKNOWN"
    # EVM hex addresses are case-insensitive identifiers; case is meaningful
    # on Base58 chains such as Solana.
    evm = str(network).strip().casefold() in ("ethereum","eth","base","arbitrum-one","polygon-pos","binance-smart-chain")
    if evm and str(a).startswith("0x") and str(b).startswith("0x"):
        return compare(a,b)
    return "MATCH" if a.strip()==b.strip() else "MISMATCH"


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
        # Independent canonical values must come from CoinGecko rather than
        # copying the staging record back into the comparison.
        cg_symbol = a.get("coingecko_symbol","") or e.get("coingecko_symbol","")
        cg_name = a.get("coingecko_name","") or e.get("coingecko_name","")
        symbol_result = compare(x.get("symbol",""),cg_symbol)
        name_result = compare(x.get("name",""),cg_name)
        canonical = ("MISMATCH" if "MISMATCH" in (name_result,symbol_result) else
                     "MATCH" if name_result=="MATCH" and symbol_result=="MATCH" else "UNKNOWN")
        project_contract=compare_contract(pc,cg_contract,pn)
        project_network="MATCH" if pn and pn in platforms else "UNKNOWN"
        exchange_identity="UNKNOWN"  # Ticker listing never proves token contract identity.
        cross_source_id = compare(a.get("coingecko_id",""),e.get("coingecko_id",""))
        gaps=[]
        if not cg_symbol: gaps.append("independent CoinGecko symbol not captured")
        if not cg_name: gaps.append("independent CoinGecko name not captured")
        if not a.get("coingecko_id") or not e.get("coingecko_id"): gaps.append("cross-source CoinGecko ID comparison unavailable")
        for label,val in [("project contract/native chain",pc or p.get("native_chain")),
                          ("official project evidence",p.get("project_evidence_url")),
                          ("independent exchange evidence",p.get("exchange_evidence_url")),
                          ("exchange asset identifier",p.get("exchange_asset_id")),
                          ("reviewer",p.get("reviewer"))]:
            if not val: gaps.append(label)
        status="PENDING"
        if any(v=="MISMATCH" for v in (canonical,project_contract,project_network,exchange_identity,cross_source_id)):
            status="AMBIGUOUS"
        row=dict.fromkeys(FIELDS,"")
        row.update(coin_id=cid,lunarcrush_symbol=x.get("symbol",""),lunarcrush_name=x.get("name",""),
            lunarcrush_network_raw=p.get("lunarcrush_network",""),
            lunarcrush_contract_raw=p.get("lunarcrush_contract",""),
            coingecko_id=e.get("coingecko_id") or a.get("coingecko_id",""),
            coingecko_symbol_raw=cg_symbol,
            coingecko_name_raw=cg_name,
            coingecko_platform_contracts_raw=json.dumps(platforms,sort_keys=True),
            coingecko_networks_raw=json.dumps(sorted(platforms)),
            project_network_raw=pn,project_contract_raw=pc,
            exchange=x.get("exchange",""),exchange_pair=x.get("pair",""),
            exchange_asset_id_raw=p.get("exchange_asset_id",""),
            exchange_network_raw=p.get("exchange_network",""),
            exchange_contract_raw=p.get("exchange_contract",""),
            staging_status=x.get("status",""),identity_candidate_status=a.get("identity_status",""),
            coingecko_listing_status=e.get("coingecko_exchange_listing",""),
            lunarcrush_canonical_comparison=canonical,
            lunarcrush_coingecko_name_comparison=name_result,
            lunarcrush_coingecko_symbol_comparison=symbol_result,
            coingecko_id_cross_source_comparison=cross_source_id,
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
