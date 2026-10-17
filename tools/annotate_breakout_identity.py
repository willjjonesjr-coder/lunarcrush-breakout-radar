"""Annotate all scored breakout candidates without identity-based suppression.

Use with an uncapped scored-candidates CSV. Never treats a ticker match as verified.
"""
import argparse
import json
from pathlib import Path
import pandas as pd

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",default="reports/breakout_radar.csv")
    p.add_argument("--audit",default="reports/asset_identity_audit.csv")
    p.add_argument("--candidates",default="reports/identity_candidates.csv")
    p.add_argument("--output",default="reports/breakout_signals_identity.csv")
    p.add_argument("--min-score",type=float,default=45)
    a=p.parse_args()
    signals=pd.read_csv(a.input,dtype={"id":str})
    if "breakout_score" not in signals: raise ValueError("Missing breakout_score")
    signals=signals[pd.to_numeric(signals.breakout_score,errors="coerce")>=a.min_score].copy()
    signals["identification_status"]="unverified"
    signals["identification_note"]="No independently verified mapping; external-price backtest blocked"
    if Path(a.audit).exists():
        audit=pd.read_csv(a.audit,dtype={"coin_id":str}).drop_duplicates("coin_id")
        mapping=audit.set_index("coin_id")["status"].to_dict()
        signals["identification_status"]=signals["id"].map(mapping).fillna("unverified")
    if Path(a.candidates).exists():
        candidates=pd.read_csv(a.candidates,dtype={"coin_id":str}).drop_duplicates("coin_id")
        ambiguous=set(candidates.loc[candidates.status.eq("ambiguous"),"coin_id"])
        signals.loc[signals.id.isin(ambiguous)&signals.identification_status.eq("unresolved"),"identification_status"]="ambiguous"
    signals.loc[signals.identification_status.eq("verified"),"identification_note"]="Approved identity mapping"
    signals.loc[signals.identification_status.eq("ambiguous"),"identification_note"]="Multiple possible identities; external-price backtest blocked"
    signals.loc[signals.identification_status.eq("excluded"),"identification_note"]="Excluded from identity backtest; breakout signal retained for review"
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    signals.sort_values("breakout_score",ascending=False).to_csv(a.output,index=False)
    print(f"Qualifying signals: {len(signals)}; no identity-status suppression; threshold: {a.min_score}")
    print(signals.identification_status.value_counts().to_string())
if __name__=="__main__": main()
