#!/usr/bin/env python3
"""Reconcile provisional 80-coin staging with canonical CoinGecko identities.

Unique exact symbol + name is only a candidate, never an approved identity.
Exchange contracts may be missing, aliases and chain migrations need review.
Does not edit approved coin mappings, histories, alerts or scanner inputs.
"""
import argparse
import csv
import json
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

URL = "https://api.coingecko.com/api/v3/coins/list?include_platform=true"
FIELDS = ("coin_id","symbol","name","exchange","pair","status","coingecko_id",
          "coingecko_name","platform_contracts","identity_status","evidence_needed","reason")

def reconcile(stage_rows, catalog, registry):
    by_symbol = defaultdict(list)
    for item in catalog:
        by_symbol[str(item.get("symbol","")).casefold()].append(item)
    output = []
    for row in stage_rows:
        cid = str(row["coin_id"])
        symbol = str(row["symbol"]).casefold()
        name = str(row["name"]).strip().casefold()
        matches = by_symbol[symbol]
        exact = [x for x in matches if str(x.get("name","")).strip().casefold() == name]
        entry = registry.get(cid,{})
        same = entry.get("status") == "verified" and entry.get("lunarcrush_symbol","").casefold()==symbol and entry.get("exchange")==row.get("exchange") and entry.get("pair")==row.get("pair") and bool(entry.get("canonical_id")) and bool(entry.get("evidence_url"))
        item = {k: row.get(k,"") for k in ("coin_id","symbol","name","exchange","pair","status")}
        canonical = exact[0] if len(exact)==1 else {}
        item.update(coingecko_id=canonical.get("id",""),
                    coingecko_name=canonical.get("name",""),
                    platform_contracts=json.dumps(canonical.get("platforms",{}),sort_keys=True),
                    identity_status=("EXISTING REGISTRY EVIDENCE — REVIEW" if same else
                                     "UNIQUE EXACT CANDIDATE — NOT VERIFIED" if len(exact)==1 else
                                     "AMBIGUOUS" if matches else "NOT FOUND"),
                    evidence_needed="LunarCrush coin ID + official contract/network or native-chain asset + exchange market/asset identity + independent evidence",
                    reason=("Exact symbol/name match only; contract and market identity unverified" if len(exact)==1 else
                            f"{len(exact)} exact name matches; {len(matches)} shared-symbol assets"))
        output.append(item)
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--staging",default="artifact-backfill/review_results.csv")
    p.add_argument("--registry",default="config/asset_identity_registry.json")
    p.add_argument("--output",default="reports/ema_identity_reconciliation.csv")
    p.add_argument("--catalog",default=None,help="Offline CoinGecko catalog JSON for reproducible testing")
    a=p.parse_args()
    with Path(a.staging).open(newline="") as f: stage=list(csv.DictReader(f))
    reg=json.loads(Path(a.registry).read_text()) if Path(a.registry).exists() else {}
    if a.catalog:
        catalog=json.loads(Path(a.catalog).read_text())
    else:
        req=urllib.request.Request(URL,headers={"User-Agent":"lunarcrush-breakout-radar/1.0","Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=45) as resp: catalog=json.load(resp)
    results=reconcile(stage,catalog,reg)
    dest=Path(a.output);dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(results)
    summary={"total":len(results),"counts":dict(Counter(row["identity_status"] for row in results)),
             "staged":sum(row["status"]=="STAGED" for row in results),"new_approved":0,
             "note":"CoinGecko unique exact match is candidate evidence only; verify contracts, chain and exchange identity independently before approval."}
    dest.with_suffix(".json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary))

if __name__=="__main__":main()
