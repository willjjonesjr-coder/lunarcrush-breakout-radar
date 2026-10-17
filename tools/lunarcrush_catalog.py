"""Fetch the Light-plan cached LunarCrush coin catalog for identity review.

Runs separately from the production scanner. The API key stays in GitHub
Secrets and is never written to reports. No guessed identity approvals.
"""
import argparse
import json
from pathlib import Path
import pandas as pd
from lunarcrush_client import LunarCrushClient

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="reports/lunarcrush_catalog.csv")
    args=parser.parse_args()
    client=LunarCrushClient()
    payload=client.get("/coins/list/v1")
    if isinstance(payload,dict):
        records=payload.get("data")
    else:
        records=payload
    if isinstance(records,dict):
        records=records.get("coins") or records.get("data")
    if not isinstance(records,list):
        raise ValueError("Unexpected LunarCrush catalog response shape; no report written")
    rows=[]
    for item in records:
        if not isinstance(item,dict): continue
        cid=item.get("id")
        symbol=item.get("symbol")
        name=item.get("name")
        if cid is None or not symbol or not name: continue
        rows.append({"coin_id":str(cid),"symbol":str(symbol),"name":str(name),
            "market_cap":item.get("market_cap"),"source":"LunarCrush /coins/list/v1"})
    if not rows: raise ValueError("Catalog contained no usable coin IDs")
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(rows).drop_duplicates("coin_id").to_csv(args.output,index=False)
    print(f"LunarCrush catalog IDs: {len(rows)}; output: {args.output}")
if __name__=="__main__": main()
