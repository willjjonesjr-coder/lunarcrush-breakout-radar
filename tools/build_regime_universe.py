#!/usr/bin/env python3
"""Build a *provisional* breadth universe from backfill inventory and radar metadata.

Symbol-matched exchange pairs are not proof of token identity. Output retains
verification status; research results must be labeled provisional.
"""
import argparse
import json
from pathlib import Path
import pandas as pd

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--inventory",default="reports/backfill_inventory.csv")
    p.add_argument("--radar",default="reports/breakout_radar.csv")
    p.add_argument("--output",default="config/market_regime_runtime_symbols.json")
    args=p.parse_args()
    inventory=pd.read_csv(args.inventory,dtype={"coin_id":str})
    radar=pd.read_csv(args.radar,dtype={"id":str})
    lookup={str(row.id):row for row in radar.itertuples()}
    mapping={"btc":{"symbol":"BTC","name":"Bitcoin","verified":True},
             "eth":{"symbol":"ETH","name":"Ethereum","verified":True}}
    used={"BTC","ETH"}
    skipped=[]
    for row in inventory.itertuples():
        cid=str(row.coin_id)
        if str(row.status) not in ("ok","partial") or cid not in lookup:
            skipped.append((cid,"missing usable history or identity"))
            continue
        identity=lookup[cid]
        symbol=str(identity.symbol).upper()
        if symbol in used or symbol in ("USDT","USDC","DAI","WBTC","WETH","RLUSD"):
            skipped.append((cid,"duplicate or excluded symbol"))
            continue
        used.add(symbol)
        mapping[cid]={"symbol":symbol,"name":str(identity.name),
                      "verified":False,"source":"LunarCrush radar symbol vs exchange base ticker"}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(mapping,indent=2)+"\n")
    print(f"Mapped {len(mapping)-2} provisional altcoins plus BTC/ETH; skipped {len(skipped)}")
    print("WARNING: Altcoin token identities are not independently verified.")
if __name__=="__main__":
    main()
