#!/usr/bin/env python3
"""Build full local asset catalog and audit explicit, evidence-backed identity mappings.

Ticker matching is never sufficient to mark an asset verified. No network access
or API credentials are required for this offline audit.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

EXCLUDED={"USDT","USDC","DAI","TUSD","FDUSD","USDE","USDS","USDD","RLUSD","WBTC","WETH","PAXG"}
REQUIRED=("exchange","pair","canonical_id","evidence_url","verified_at")

def audit(data_dir,radar_path,registry_path):
    radar=pd.read_csv(radar_path,dtype={"id":str})
    radar=radar.dropna(subset=["id","symbol"]).drop_duplicates("id",keep="last")
    lookup={str(r.id):r for r in radar.itertuples()}
    history={}
    for path in sorted(Path(data_dir).glob("history_*.csv")):
        cid=path.stem.removeprefix("history_")
        try:
            frame=pd.read_csv(path,usecols=["market_cap"])
            values=pd.to_numeric(frame.market_cap,errors="coerce").dropna()
            history[cid]=float(values.iloc[-1]) if not values.empty else 0.
        except (ValueError,OSError,pd.errors.EmptyDataError):
            history[cid]=0.
    registry=json.loads(Path(registry_path).read_text()) if Path(registry_path).exists() else {}
    rows=[]
    for cid in sorted(set(lookup)|set(history)):
        entry=registry.get(cid,{})
        identity=lookup.get(cid)
        symbol=str(identity.symbol).upper() if identity is not None else ""
        name=str(identity.name) if identity is not None else ""
        reason=""
        if symbol in EXCLUDED:
            status="excluded";reason="excluded asset type"
        elif not symbol:
            status="unresolved";reason="missing LunarCrush symbol"
        elif entry.get("status")=="excluded":
            status="excluded";reason="registry exclusion"
        elif entry.get("status")=="verified":
            missing=[k for k in REQUIRED if not entry.get(k)]
            try:
                verified_date=datetime.fromisoformat(str(entry.get("verified_at","")).replace("Z","+00:00"))
                if verified_date.tzinfo is None: missing.append("verified_at timezone")
            except ValueError: missing.append("verified_at format")
            if entry.get("lunarcrush_symbol","").upper()!=symbol: missing.append("lunarcrush_symbol mismatch")
            if not str(entry.get("pair","")).endswith(("/USD","/USDT")): missing.append("supported quote")
            if str(entry.get("pair","")).split("/")[0].upper()!=str(entry.get("exchange_base",symbol)).upper(): missing.append("exchange_base mismatch")
            status="ambiguous" if missing else "verified"
            reason="; ".join(missing)
        elif entry:
            status="ambiguous";reason="registry entry lacks approved evidence"
        else:
            status="unresolved";reason="no independently verified identity"
        rows.append(dict(coin_id=cid,symbol=symbol,name=name,market_cap=history.get(cid,0),
                         has_history=cid in history,status=status,reason=reason,
                         canonical_id=entry.get("canonical_id",""),exchange=entry.get("exchange",""),
                         pair=entry.get("pair",""),evidence_url=entry.get("evidence_url","")))
    return pd.DataFrame(rows).sort_values(["market_cap","coin_id"],ascending=[False,True])

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="data")
    p.add_argument("--radar",default="reports/breakout_radar.csv")
    p.add_argument("--registry",default="config/asset_identity_registry.json")
    p.add_argument("--output",default="reports/asset_identity_audit.csv")
    a=p.parse_args()
    df=audit(a.data_dir,a.radar,a.registry)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    df.to_csv(a.output,index=False)
    print(f"Catalog assets: {len(df)}; local histories: {df.has_history.sum()}")
    print(df.status.value_counts().to_string())
    print("Verification requires independent evidence; matching tickers alone is insufficient.")
if __name__=="__main__": main()
