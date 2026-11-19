"""Reconstruct 47 incremental 500-bar candidates from a specified smoke artifact.

Fail closed if the artifact's cohort, provenance, incremental IDs or venue
readiness disagree. No production files are written.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from tools.compare_cex_coverage import ORIGINAL, ADDED

READY = "500_BAR_READY_PROVISIONAL"
FIELDS = ("priority_rank", "coin_id", "symbol", "name", "radar_score",
          "source_count", "source_markets", "source_exchanges", "primary_source_markets",
          "priority_group", "history_status", "identity_status",
          "production_approval", "alert_eligible")


def reconstruct(diversity, coverage, expected_count=47, expected_cohort=200):
    if diversity.get("cohort_coins") != expected_cohort:
        raise ValueError("source cohort size mismatch")
    if diversity.get("incremental_500_unique_coins_vs_original_three") != expected_count:
        raise ValueError("source incremental 500 count mismatch")
    source_ids = diversity.get("incremental_500_coin_ids", [])
    if len(source_ids) != len(set(source_ids)) or len(source_ids) != expected_count:
        raise ValueError("source incremental ID count or uniqueness mismatch")
    grouped = defaultdict(list)
    for r in coverage:
        cid = str(r.get("coin_id") or "")
        if cid:
            grouped[cid].append(r)
    if len(grouped) != expected_cohort:
        raise ValueError("coverage rows do not match source cohort")
    results = []
    for cid in source_ids:
        group = grouped.get(str(cid))
        if not group:
            raise ValueError("missing candidate in coverage: " + str(cid))
        if any(r.get("history_status") == READY and r.get("exchange") in ORIGINAL for r in group):
            raise ValueError("candidate not incremental to original exchanges: " + str(cid))
        matches = [r for r in group
                   if r.get("exchange") in ADDED
                   and r.get("history_status") == READY
                   and r.get("market_status") == "FOUND_PROVISIONAL"
                   and r.get("approval_status") == "RESEARCH_ONLY_DO_NOT_IMPORT"
                   and r.get("identity_status") == "UNVERIFIED_SYMBOL_MATCH_ONLY"]
        identities = {(r.get("symbol"), r.get("name")) for r in group}
        if len(identities) != 1:
            raise ValueError("conflicting candidate symbol/name: " + str(cid))
        sym, name = next(iter(identities))
        if not sym:
            raise ValueError("missing symbol: " + str(cid))
        by_venue = defaultdict(list)
        for r in matches:
            pair = r.get("pair") or ""
            base, slash, quote = pair.partition("/")
            if (slash != "/" or ":" in quote or base.upper() != sym.upper()
                    or quote.upper() not in {"USD", "USDT", "USDC"}):
                raise ValueError("invalid spot base/quote: " + str(cid))
            by_venue[r["exchange"]].append(r)
        if not by_venue:
            raise ValueError("no 500-bar provisional source: " + str(cid))
        # One deterministic best source per exchange; prefer more bars and USD.
        sources = []
        for venue, candidates in sorted(by_venue.items()):
            candidates.sort(key=lambda r: (-int(r.get("bars_available") or 0),
                                           {"USD": 0, "USDT": 1, "USDC": 2}.get(r["pair"].split("/")[1].upper(), 9),
                                           r["pair"]))
            sources.append(venue + ":" + candidates[0]["pair"])
        # The cohort is incremental at 500 bars, but a primary venue may still
        # offer enough recent daily closes for independent corroboration.
        primary = []
        for venue in ORIGINAL:
            choices = [r for r in group
                       if r.get("exchange") == venue
                       and r.get("market_status") == "FOUND_PROVISIONAL"
                       and r.get("identity_status") == "UNVERIFIED_SYMBOL_MATCH_ONLY"
                       and r.get("approval_status") == "RESEARCH_ONLY_DO_NOT_IMPORT"
                       and r.get("history_status") not in ("INVALID_OHLCV", "NOT_SAMPLED")]
            valid = []
            for r in choices:
                pair = str(r.get("pair") or "")
                base, sep, quote = pair.partition("/")
                if sep == "/" and ":" not in quote and base.upper() == sym.upper() and quote.upper() in ("USD", "USDT", "USDC"):
                    valid.append(r)
            valid.sort(key=lambda r: ({"USD":0,"USDT":1,"USDC":2}[r["pair"].split("/")[1].upper()],
                                      -int(r.get("bars_available") or 0), r["pair"]))
            if valid:
                primary.append(venue + ":" + valid[0]["pair"])
        score_raw = group[0].get("breakout_score") or "0"
        try:
            score = float(score_raw)
        except ValueError:
            score = 0.0
        results.append(dict(coin_id=str(cid), symbol=sym, name=name,
                            radar_score=score, source_count=len(sources),
                            source_markets=";".join(sources),
                            primary_source_markets=";".join(primary),
                            source_exchanges=";".join(sorted(by_venue)),
                            priority_group="MULTI_EXCHANGE" if len(sources) >= 2 else "SINGLE_EXCHANGE",
                            history_status=READY, identity_status="UNVERIFIED_RESEARCH_ONLY",
                            production_approval="NO", alert_eligible="NO"))
    results.sort(key=lambda r: (r["source_count"] < 2, -r["source_count"],
                                -r["radar_score"], r["coin_id"]))
    for i, r in enumerate(results, 1):
        r["priority_rank"] = i
    return results


def write(source, output, expected_count=47, expected_cohort=200):
    path = Path(source)
    diversity = json.loads((path / "reports/historical_exchange_diversity.json").read_text())
    with (path / "reports/expanded_cex_coverage.csv").open(newline="") as f:
        coverage = list(csv.DictReader(f))
    rows = reconstruct(diversity, coverage, expected_count, expected_cohort)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "candidates.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = dict(candidates=len(rows),
                   multiple_exchange=sum(r["source_count"] >= 2 for r in rows),
                   single_exchange=sum(r["source_count"] == 1 for r in rows),
                   identities_verified=0, production_approvals=0,
                   policy="Source run only; exchange matching is research-only.")
    (out / "candidates.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--output", default="reports/47_cex_research_input")
    p.add_argument("--expected-count", type=int, default=47)
    p.add_argument("--expected-cohort", type=int, default=200)
    a = p.parse_args()
    print(json.dumps(write(a.source, a.output, a.expected_count, a.expected_cohort), indent=2))


if __name__ == "__main__":
    main()
