#!/usr/bin/env python3
"""Build a ranked, ID-safe research queue for missing production EMA coverage.

This only prepares discovery targets; a spot ticker match is not identity proof.
The original 41 research-ready assets are not rescanned or silently promoted.
"""
import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

TARGETS = {"NO_MATCHING_RESEARCH_ARTIFACT", "UNCLASSIFIED_MISSING_EMA"}
FIELDS = ("review_rank", "coin_id", "symbol", "name", "breakout_score",
          "coverage_blocker", "market_cap", "volume_24h_snapshot",
          "liquidity_label", "identity_status", "research_only")


def read(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build(coverage, production, count=40):
    if not 1 <= count <= 300:
        raise ValueError("Batch size must be between 1 and 300")
    prod, duplicates = {}, set()
    for r in production:
        cid = str(r.get("id") or "").strip()
        if not cid:
            continue
        if cid in prod:
            duplicates.add(cid)
        else:
            prod[cid] = r
    seen, output, skipped = set(), [], Counter()
    for row in coverage:
        cid = str(row.get("coin_id") or "").strip()
        if not cid or cid in seen:
            raise ValueError("Coverage has missing or duplicate coin ID: " + cid)
        seen.add(cid)
        blocker = str(row.get("primary_blocker") or "")
        if blocker not in TARGETS:
            skipped["OTHER_COVERAGE_CATEGORY"] += 1
            continue
        ref = prod.get(cid)
        if cid in duplicates or ref is None or ref.get("history_selection") != "ANALYZED":
            skipped["SOURCE_PRODUCTION_MISSING_OR_DUPLICATED"] += 1
            continue
        if any(str(ref.get(k) or "").strip().casefold() !=
               str(row.get(k) or "").strip().casefold() for k in ("name", "symbol")):
            skipped["NAME_SYMBOL_CONFLICT"] += 1
            continue
        if any(str(ref.get("ema"+str(n)) or "").strip() for n in (50,100,200)):
            skipped["PRODUCTION_EMA_ALREADY_PRESENT"] += 1
            continue
        try:
            score = float(row.get("breakout_score") or ref.get("breakout_score") or 0)
        except (ValueError,TypeError):
            score = 0.
        if not math.isfinite(score):
            raise ValueError("Nonfinite score: " + cid)
        if not str(row.get("symbol") or "").strip():
            skipped["MISSING_SYMBOL"] += 1
            continue
        output.append({
            "review_rank": 0, "coin_id": cid,
            "symbol": row.get("symbol"), "name": row.get("name"),
            "breakout_score": round(score,6),
            "coverage_blocker": blocker,
            "market_cap": ref.get("market_cap",""),
            "volume_24h_snapshot": ref.get("volume_24h_snapshot",""),
            "liquidity_label": ref.get("liquidity_label",""),
            "identity_status": row.get("identity_status") or "UNKNOWN",
            "research_only": "YES",
        })
    output.sort(key=lambda x: (-x["breakout_score"], x["coin_id"]))
    for i,r in enumerate(output,1):
        r["review_rank"]=i
    chosen=output[:count]
    return output, chosen, {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "eligible_discovery_targets": len(output),
        "requested_batch": count, "selected_batch": len(chosen),
        "eligible_blockers": dict(sorted(Counter(r["coverage_blocker"] for r in output).items())),
        "skipped": dict(sorted(skipped.items())),
        "production_approvals":0, "alerts":0,
        "policy":"Lower-cap targets retained; ticker/spot pair and OHLCV are discovery only, not coin identity."
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--coverage",required=True)
    p.add_argument("--production",required=True,
                   help="Pinned production CSV from the coverage audit source commit")
    p.add_argument("--count",type=int,default=40)
    p.add_argument("--output",default="reports/ema_coverage_expansion")
    a=p.parse_args()
    universe,queue,summary=build(read(a.coverage),read(a.production),a.count)
    out=Path(a.output)
    out.mkdir(parents=True,exist_ok=True)
    for filename,items in (("all_targets.csv",universe),("selected_batch.csv",queue)):
        with (out/filename).open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS)
            w.writeheader()
            w.writerows(items)
    (out/"research_queue.json").write_text(json.dumps({
        "as_of_utc":summary["generated_at_utc"],
        "first_review_batch":queue,
        "policy":summary["policy"]
    },indent=2)+"\n",encoding="utf-8")
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
