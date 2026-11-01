"""Collect independent market listing evidence for 30 unique EMA identity candidates.

Research only: an exchange ticker listing does NOT verify contract or chain identity.
No mapping, pricing or alert modifications.
"""
import csv
import argparse
import os
import random
import urllib.error
from datetime import datetime, timezone
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

SOURCE=Path("artifact-review/ema_staged_identity_review.csv")
OUT=Path("reports/ema_identity_evidence_30.csv")
FIELDS=["coin_id","symbol","name","coingecko_id","exchange","pair",
        "coingecko_exchange_listing","coin_platforms","evidence_url",
        "status","reason"]
EXCHANGE_NAMES={"kraken":"Kraken","coinbase":"Coinbase Exchange","binance":"Binance"}

def fetch(url, attempts=5, base_delay=12, sleep=time.sleep):
    req=urllib.request.Request(url,headers={"User-Agent":"ema-identity-research/1.0","Accept":"application/json"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req,timeout=35) as f:
                return json.load(f)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==attempts-1:
                raise
            retry=exc.headers.get("Retry-After")
            try:
                delay=max(0,min(180,float(retry))) if retry else min(180,base_delay*2**attempt)
            except (ValueError, TypeError):
                delay=min(180,base_delay*2**attempt)
            print(f"CoinGecko HTTP {exc.code}; retry {attempt+1}/{attempts-1} after {delay:.0f}s",flush=True)
            sleep(delay)
        except (urllib.error.URLError,TimeoutError) as exc:
            if attempt==attempts-1:
                raise
            sleep(min(180,base_delay*2**attempt))
    raise RuntimeError("Retry budget exhausted")

def check(row):
    cid=row.get("coingecko_id","")
    result={k:row.get(k,"") for k in ("coin_id","symbol","name","coingecko_id","exchange","pair")}
    result.update(coingecko_exchange_listing="NOT CHECKED",coin_platforms="",
                  evidence_url="",status="MANUAL EVIDENCE REQUIRED",reason="")
    if row.get("decision")!="REVIEW UNIQUE CANONICAL CANDIDATE" or not cid:
        result["reason"]="Ambiguous or missing canonical identity"
        return result
    url="https://api.coingecko.com/api/v3/coins/"+urllib.parse.quote(cid,safe="")+"?localization=false&tickers=true&market_data=false&community_data=false&developer_data=false"
    result["evidence_url"]=url
    try:
        data=fetch(url)
        platforms=data.get("detail_platforms") or {}
        result["coin_platforms"]=json.dumps({k:v.get("contract_address","") for k,v in platforms.items() if isinstance(v,dict)},sort_keys=True)
        base,_,quote=row.get("pair","").partition("/")
        target=EXCHANGE_NAMES.get(row.get("exchange",""),"")
        tickers=data.get("tickers") or []
        found=any(str(t.get("market",{}).get("name","")).casefold()==target.casefold()
                  and str(t.get("base","")).casefold()==base.casefold()
                  and str(t.get("target","")).casefold()==quote.casefold()
                  for t in tickers)
        result["coingecko_exchange_listing"]="FOUND" if found else "NOT FOUND IN RETURNED TICKERS"
        result["reason"]="Check official project contract/native chain and exchange asset identifiers before approval; ticker API may be paginated"
    except Exception as e:
        result["coingecko_exchange_listing"]="LOOKUP ERROR"
        result["reason"]=f"{type(e).__name__}: {e}"[:180]
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--resume",default="",help="Previous evidence CSV; reuse successful results")
    parser.add_argument("--delay",type=float,default=15,help="Seconds between new API requests")
    args=parser.parse_args()
    with SOURCE.open(newline="") as f: rows=list(csv.DictReader(f))
    selected=[x for x in rows if x.get("decision")=="REVIEW UNIQUE CANONICAL CANDIDATE"]
    previous={}
    if args.resume and Path(args.resume).exists():
        with Path(args.resume).open(newline="") as f:
            previous={str(r["coin_id"]):r for r in csv.DictReader(f)}
    output=[]
    OUT.parent.mkdir(parents=True,exist_ok=True)
    for row in selected:
        cid=str(row["coin_id"])
        old=previous.get(cid)
        same=(old and all(str(old.get(k,""))==str(row.get(k,"")) for k in ("symbol","name","coingecko_id","exchange","pair")))
        if same and old.get("coingecko_exchange_listing") not in ("LOOKUP ERROR","NOT CHECKED",""):
            entry={key:old.get(key,"") for key in FIELDS}
            print(cid,"CACHED",entry["coingecko_exchange_listing"],flush=True)
        else:
            if any(x.get("_fetched") for x in output):
                time.sleep(max(args.delay,0))
            entry=check(row)
            entry["_fetched"]=True
            print(cid,entry["coingecko_exchange_listing"],flush=True)
        output.append(entry)
        # Save progress after each asset; interrupted workflows can resume.
        with OUT.open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="ignore")
            writer.writeheader();writer.writerows(output)
    summary={"candidates":len(selected),
             "exchange_listings_found":sum(x["coingecko_exchange_listing"]=="FOUND" for x in output),
             "lookup_errors":sum(x["coingecko_exchange_listing"]=="LOOKUP ERROR" for x in output),
             "approved":0,"policy":"Research evidence only; no automated identity approvals or production imports."}
    OUT.with_suffix(".json").write_text(json.dumps(summary,indent=2)+"\n")
    print(summary)

if __name__=="__main__":main()
