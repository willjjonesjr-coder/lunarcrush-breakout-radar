"""Discover candidate CoinGecko identities; candidates require manual review."""
import argparse
from pathlib import Path
import pandas as pd
import requests

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--limit",type=int,default=90)
    args=parser.parse_args()
    radar=pd.read_csv("reports/breakout_radar.csv",dtype={"id":str}).dropna(subset=["id","symbol","name"])
    response=requests.get("https://api.coingecko.com/api/v3/coins/list",params={"include_platform":"true"},timeout=45)
    response.raise_for_status()
    catalog=response.json()
    index={}
    for item in catalog:
        index.setdefault(str(item.get("symbol","")).casefold(),[]).append(item)
    results=[]
    for row in radar.drop_duplicates("id").head(args.limit).itertuples():
        matches=index.get(str(row.symbol).casefold(),[])
        exact=[m for m in matches if str(m.get("name","")).casefold()==str(row.name).casefold()]
        results.append({"coin_id":row.id,"symbol":row.symbol,"name":row.name,
            "coingecko_id":exact[0]["id"] if len(exact)==1 else "",
            "contract_platforms":str(exact[0].get("platforms",{})) if len(exact)==1 else "",
            "status":"review_required" if len(exact)==1 else "ambiguous" if matches else "unresolved",
            "ticker_matches":len(matches),"exact_name_matches":len(exact),
            "reason":"Ticker and name are discovery hints, not proof of identity"})
    Path("reports").mkdir(exist_ok=True)
    pd.DataFrame(results).to_csv("reports/identity_candidates.csv",index=False)
    print(pd.DataFrame(results).status.value_counts().to_string())
    print("Zero assets automatically approved")
if __name__=="__main__":
    main()
