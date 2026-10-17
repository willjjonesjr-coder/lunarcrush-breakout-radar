"""Discover CoinGecko identity candidates across all locally known coin IDs.

Only evidence-backed records can be approved separately; this script never
writes to the verified registry. Unknown LunarCrush metadata stays unresolved.
"""
import argparse
import json
from pathlib import Path
import pandas as pd
import requests

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--limit",type=int,default=0,help="0 means all assets")
    args=parser.parse_args()
    radar=pd.read_csv("reports/breakout_radar.csv",dtype={"id":str}).dropna(subset=["id","symbol","name"])
    radar=radar.drop_duplicates("id")
    known={str(row.id):{"symbol":str(row.symbol),"name":str(row.name)} for row in radar.itertuples()}
    catalog_path=Path("reports/lunarcrush_catalog.csv")
    if catalog_path.exists():
        lunar=pd.read_csv(catalog_path,dtype={"coin_id":str}).dropna(subset=["coin_id","symbol","name"])
        for row in lunar.drop_duplicates("coin_id").itertuples():
            known[str(row.coin_id)]={"symbol":str(row.symbol),"name":str(row.name)}

    history={p.stem.removeprefix("history_") for p in Path("data").glob("history_*.csv")}
    ids=sorted(history)
    if args.limit>0: ids=ids[:args.limit]
    response=requests.get("https://api.coingecko.com/api/v3/coins/list",params={"include_platform":"true"},timeout=45)
    response.raise_for_status()
    catalog=response.json()
    index={}
    for item in catalog:
        index.setdefault(str(item.get("symbol","")).casefold(),[]).append(item)
    results=[]
    for cid in ids:
        row=known.get(cid)
        if row is None:
            results.append({"coin_id":cid,"symbol":"","name":"","coingecko_id":"",
                "contract_platforms":"","status":"unresolved","ticker_matches":0,
                "exact_name_matches":0,"reason":"Missing LunarCrush metadata; obtain full catalog before matching"})
            continue
        matches=index.get(row["symbol"].casefold(),[])
        exact=[m for m in matches if str(m.get("name","")).casefold()==row["name"].casefold()]
        results.append({"coin_id":cid,"symbol":row["symbol"],"name":row["name"],
            "coingecko_id":exact[0]["id"] if len(exact)==1 else "",
            "contract_platforms":json.dumps(exact[0].get("platforms") or {},sort_keys=True) if len(exact)==1 else "",
            "status":"review_required" if len(exact)==1 else "ambiguous" if matches else "unresolved",
            "ticker_matches":len(matches),"exact_name_matches":len(exact),
            "reason":"Ticker/name match is not proof; confirm chain or contract and exchange asset independently"})
    Path("reports").mkdir(exist_ok=True)
    df=pd.DataFrame(results)
    df.to_csv("reports/identity_candidates.csv",index=False)
    print(f"Historical IDs: {len(ids)}; LunarCrush metadata: {sum(cid in known for cid in ids)}; catalog loaded: {catalog_path.exists()}")
    print(df.status.value_counts().to_string())
    print("Zero assets automatically approved")
if __name__=="__main__": main()
