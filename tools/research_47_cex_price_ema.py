"""Multi-venue, price-corroborated provisional EMA research for 47 candidates.

Uses PR #60's exact UTC-day LunarCrush comparison and validated 500-bar
CCXT fetcher. All outcomes remain UNVERIFIED and research-only. No production
imports, approved maps, scanner scores or alert fields are modified.
"""
import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from provisional_ema import fetch_history, provisional_technicals
from tools.research_price_corroborated_ema import (
    evaluate_prices, reference_history, parse_sources, known_conflict,
)

AUDIT_FIELDS = ("priority_rank", "coin_id", "symbol", "name", "source_count",
                "exchange", "pair", "quote", "status", "reason", "history_bars",
                "comparison_days", "reference_prices", "exchange_prices",
                "daily_difference_pct", "max_difference_pct",
                "mean_difference_pct", "production_approval", "alert_eligible")
SUMMARY_FIELDS = ("priority_rank", "coin_id", "symbol", "name", "source_count",
                  "sources_checked", "sources_corrob", "source_disagreements",
                  "corroboration_status", "ema_status", "ema50", "ema100",
                  "ema200", "research_csv", "reason", "production_approval",
                  "alert_eligible")


def check_candidate(item, histories, client_for, required_day, conflicts,
                    max_sources=3, tolerance_pct=2.0):
    """One coin: do not promote on any observed price conflict.

    Evaluate each selected distinct venue against LunarCrush's latest five
    completed days; require >=3 consecutive aligned completed dates and <=2%
    absolute differences on *every* matched date. A multi-venue candidate
    needs two corroborating exchanges; single-venue results stay distinct.
    """
    cid = str(item["coin_id"])
    sources = parse_sources(item)[:max_sources]
    ref_path = Path(histories) / ("history_" + cid + ".csv")
    base = {k: item.get(k, "") for k in ("priority_rank", "coin_id", "symbol", "name", "source_count")}
    result = dict(base, sources_checked=0, sources_corrob=0, source_disagreements=0,
                  corroboration_status="NOT_EVALUATED", ema_status="NOT_EVALUATED",
                  ema50="", ema100="", ema200="", research_csv="", reason="",
                  production_approval="NO", alert_eligible="NO")
    audit = []
    def add(venue="", pair="", status="NOT_EVALUATED", reason="", checks=None, n=0):
        checks = checks or []
        audit.append(dict(base, exchange=venue, pair=pair,
                          quote=pair.partition("/")[2], status=status, reason=reason,
                          history_bars=n,
                          comparison_days=";".join(c["day"] for c in checks),
                          reference_prices=json.dumps([c["reference"] for c in checks]),
                          exchange_prices=json.dumps([c["exchange"] for c in checks]),
                          daily_difference_pct=json.dumps([round(c["difference_pct"], 8) for c in checks]),
                          max_difference_pct=max((c["difference_pct"] for c in checks), default=""),
                          mean_difference_pct=(sum(c["difference_pct"] for c in checks) / len(checks)) if checks else "",
                          production_approval="NO", alert_eligible="NO"))
    conflict = known_conflict(item, conflicts)
    if conflict:
        result.update(corroboration_status="IDENTITY_CONFLICT", reason=conflict)
        add(status="IDENTITY_CONFLICT", reason=conflict)
        return result, audit, None
    if not ref_path.exists():
        result.update(corroboration_status="MISSING_REFERENCE", reason="LunarCrush history unavailable")
        add(status="MISSING_REFERENCE", reason=result["reason"])
        return result, audit, None
    if not sources:
        result.update(corroboration_status="NO_VALID_SOURCES", reason="No exact supported spot base/quote")
        add(status="NO_VALID_SOURCES", reason=result["reason"])
        return result, audit, None
    try:
        reference = reference_history(ref_path, cid)
    except ValueError as exc:
        result.update(corroboration_status="IDENTITY_CONFLICT", reason=str(exc))
        add(status="IDENTITY_CONFLICT", reason=str(exc))
        return result, audit, None

    good, bad, issues = [], [], []
    for venue, pair in sources:
        result["sources_checked"] += 1
        candles = []
        try:
            client = client_for(venue)
            # PR #60 fetcher validates active exact spot pair and complete
            # contiguous daily OHLCV ending yesterday, excluding live candles.
            candles = fetch_history(client, pair, required_day, 500)
            exchange_closes = {datetime.fromisoformat(str(c[0])[:10]).date(): float(c[4]) for c in candles}
            verdict = evaluate_prices(reference, exchange_closes, required_day,
                                      tolerance_pct=tolerance_pct, minimum_days=3, window=5)
            status = verdict["status"]
            reason = verdict["reason"]
            add(venue, pair, status, reason, verdict.get("checks"), len(candles))
            if status == "PRICE_CORROBORATED":
                good.append((venue, pair, candles))
            elif status in ("PRICE_MISMATCH", "CONFLICT", "INVALID_EXCHANGE_PRICE",
                            "INVALID_REFERENCE_PRICE"):
                bad.append(venue + ":" + status)
            else:
                issues.append(venue + ":" + status)
        except Exception as exc:
            reason = type(exc).__name__ + ": " + str(exc)[:200]
            add(venue, pair, "SOURCE_ERROR", reason, n=len(candles))
            issues.append(venue + ":SOURCE_ERROR")

    result["sources_corrob"] = len(good)
    result["source_disagreements"] = len(bad)
    required_good = 2 if int(item.get("source_count") or 0) >= 2 else 1
    if bad:
        result.update(corroboration_status="PRICE_CONFLICT_REVIEW",
                      reason="Observed source disagreement: " + ";".join(bad))
    elif len(good) < required_good:
        result.update(corroboration_status="INSUFFICIENT_CORROBORATION",
                      reason=f"{len(good)}/{required_good} required venues agree; " + ";".join(issues))
    else:
        result.update(corroboration_status=("PRICE_CORROBORATED_MULTI_SOURCE"
                                          if required_good == 2 else "PRICE_CORROBORATED_SINGLE_SOURCE"),
                      reason="LunarCrush exact-day close comparison passed; canonical identity and liquidity unverified")
        selected = good[0]
        technicals = provisional_technicals(selected[2])
        result.update(ema_status=technicals["provisional_technical_status"],
                      ema50=technicals["provisional_ema50"],
                      ema100=technicals["provisional_ema100"],
                      ema200=technicals["provisional_ema200"])
        return result, audit, selected
    return result, audit, None


def write_report(input_csv, history_dir, output, today=None, max_sources=3,
                 tolerance_pct=2.0, conflicts=None, client_factory=None):
    if not 1 <= max_sources <= 3 or not 0 < tolerance_pct <= 2.0:
        raise ValueError("sources must be 1-3 and provisional tolerance <=2%")
    today = today or datetime.now(timezone.utc).date()
    required_day = today - timedelta(days=1)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    price_dir = out / "provisional_ema"
    price_dir.mkdir(exist_ok=True)
    with open(input_csv, newline="") as f:
        items = list(csv.DictReader(f))
    if len(items) != 47 or len({x["coin_id"] for x in items}) != 47:
        raise ValueError("expected exactly 47 distinct candidates")
    if client_factory is None:
        import ccxt
        client_factory = lambda venue: getattr(ccxt, venue)({"enableRateLimit": True, "timeout": 30000})
    clients = {}
    def client_for(venue):
        if venue not in clients:
            client = client_factory(venue)
            client.load_markets()
            clients[venue] = client
        return clients[venue]
    report_rows, audit_rows = [], []
    for item in items:
        result, checks, selected = check_candidate(item, history_dir, client_for,
                              required_day, conflicts or {}, max_sources, tolerance_pct)
        if selected is not None:
            venue, pair, candles = selected
            target = price_dir / (str(item["coin_id"]) + ".csv")
            with target.open("w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(("time", "open", "high", "low", "close", "volume", "exchange", "pair"))
                writer.writerows([*c, venue, pair] for c in candles)
            result["research_csv"] = str(target)
        report_rows.append(result)
        audit_rows.extend(checks)
        # Preserve intermediate evidence for partial workflow failures.
        _write_csv(out / "source_price_audit.csv", AUDIT_FIELDS, audit_rows)
        _write_csv(out / "provisional_ema_summary.csv", SUMMARY_FIELDS, report_rows)
    counts = {}
    for result in report_rows:
        status = result["corroboration_status"]
        counts[status] = counts.get(status, 0) + 1
    summary = {"source_candidates": len(items), "multi_exchange_candidates":
               sum(int(x["source_count"]) >= 2 for x in items),
               "single_exchange_candidates": sum(int(x["source_count"]) == 1 for x in items),
               "statuses": counts, "source_checks": len(audit_rows), "fully_verified": 0,
               "production_approvals": 0, "alerts": 0, "completed_day": required_day.isoformat(),
               "tolerance_pct": tolerance_pct, "minimum_consecutive_dates": 3,
               "policy": "Research only; price agreement does not verify canonical identity. "
                         "Exact UTC closes and source-by-source differences are archived; "
                         "no production imports or alerts."}
    (out / "provisional_ema_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def _write_csv(path, columns, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, columns)
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="reports/47_cex_research_input/candidates.csv")
    p.add_argument("--history-dir", default="data")
    p.add_argument("--output", default="reports/47_cex_price_research")
    p.add_argument("--conflicts", default="config/price_corroboration_conflicts.json")
    p.add_argument("--max-sources", type=int, default=3)
    a = p.parse_args()
    conflicts = json.loads(Path(a.conflicts).read_text())
    print(json.dumps(write_report(a.input, a.history_dir, a.output,
                                  max_sources=a.max_sources, conflicts=conflicts), indent=2))


if __name__ == "__main__":
    main()
