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
from tools.audit_expanded_cex_coverage import markets_for_coin
from tools.research_price_corroborated_ema import (
    evaluate_prices, reference_history, parse_sources, known_conflict,
)

PRIMARY = ("coinbase", "kraken", "binance")
QUOTES = {"USD", "USDT", "USDC"}


def primary_sources(item):
    """Only exact-base spot pairs recorded by the nine-CEX source audit."""
    symbol = str(item.get("symbol") or "").upper()
    entries = {}
    for source in str(item.get("primary_source_markets") or "").split(";"):
        venue, sep, pair = source.partition(":")
        if not sep or venue not in PRIMARY or venue in entries:
            continue
        base, slash, quote = pair.partition("/")
        if slash == "/" and ":" not in quote and base.upper() == symbol and quote.upper() in QUOTES:
            entries[venue] = pair
    return entries


AUDIT_FIELDS = ("priority_rank", "coin_id", "symbol", "name", "source_count",
                "exchange", "pair", "quote", "status", "reason", "history_bars",
                "comparison_days", "reference_prices", "exchange_prices",
                "daily_difference_pct", "max_difference_pct",
                "mean_difference_pct", "production_approval", "alert_eligible")
SUMMARY_FIELDS = ("priority_rank", "coin_id", "symbol", "name", "source_count",
                  "sources_checked", "sources_corrob", "source_disagreements",
                  "primary_venues_checked", "primary_venues_corrob",
                  "corroboration_status", "ema_status", "ema50", "ema100",
                  "ema200", "research_csv", "reason", "production_approval",
                  "alert_eligible")


def check_candidate(item, histories, client_for, required_day, conflicts,
                    max_sources=3, tolerance_pct=2.0):
    """Check Coinbase, Kraken, Binance first, then fallback venues.

    Primary comparisons need only 3 contiguous recent daily OHLCV bars, not
    500; 500 validated bars remain mandatory for an EMA candle source.
    Two passing primary venues prevail over a third *price* disagreement,
    but no explicit identity conflict or uncorroborated 500-bar series passes.
    """
    cid = str(item["coin_id"])
    primary = primary_sources(item)
    fallback = parse_sources(item)[:max_sources]
    ref_path = Path(histories) / ("history_" + cid + ".csv")
    base = {k: item.get(k, "") for k in ("priority_rank", "coin_id", "symbol", "name", "source_count")}
    result = dict(base, sources_checked=0, sources_corrob=0, source_disagreements=0,
                  primary_venues_checked=0, primary_venues_corrob=0,
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
    if not fallback and not primary:
        result.update(corroboration_status="NO_VALID_SOURCES", reason="No exact supported spot base/quote")
        add(status="NO_VALID_SOURCES", reason=result["reason"])
        return result, audit, None
    try:
        reference = reference_history(ref_path, cid)
    except ValueError as exc:
        result.update(corroboration_status="IDENTITY_CONFLICT", reason=str(exc))
        add(status="IDENTITY_CONFLICT", reason=str(exc))
        return result, audit, None

    primary_good, fallback_good, bad, issues = [], [], [], []

    def inspect(venue, pair, bars):
        result["sources_checked"] += 1
        candles = []
        try:
            client = client_for(venue)
            candles = fetch_history(client, pair, required_day, bars)
            closes = {datetime.fromisoformat(str(c[0])[:10]).date(): float(c[4])
                      for c in candles}
            verdict = evaluate_prices(reference, closes, required_day,
                                      tolerance_pct=tolerance_pct, minimum_days=3, window=5)
            add(venue, pair, verdict["status"], verdict["reason"],
                verdict.get("checks"), len(candles))
            if verdict["status"] == "PRICE_CORROBORATED":
                return (venue, pair, candles)
            if verdict["status"] in ("PRICE_MISMATCH", "CONFLICT",
                                     "INVALID_EXCHANGE_PRICE", "INVALID_REFERENCE_PRICE"):
                bad.append(venue + ":" + verdict["status"])
            else:
                issues.append(venue + ":" + verdict["status"])
        except Exception as exc:
            reason = type(exc).__name__ + ": " + str(exc)[:200]
            add(venue, pair, "SOURCE_ERROR", reason, n=len(candles))
            issues.append(venue + ":SOURCE_ERROR")
        return None

    # Inspect every primary venue in strict order, including absent or failed
    # listings. No secondary exchange may be queried during this phase.
    for venue in PRIMARY:
        result["primary_venues_checked"] += 1
        pair = primary.get(venue)
        if not pair:
            # Live retry: an unavailable or unlisted venue in the older source
            # artifact must not be silently treated as checked today.
            try:
                client = client_for(venue)
                matches = markets_for_coin(client, str(item.get("symbol") or "").upper())
                if matches:
                    pair = matches[0]["symbol"]
                else:
                    add(venue, status="NO_EXACT_SPOT_PAIR",
                        reason="No active exact-base USD/USDT/USDC spot market")
                    continue
            except Exception as exc:
                add(venue, status="PRIMARY_EXCHANGE_UNAVAILABLE",
                    reason=type(exc).__name__ + ": " + str(exc)[:180])
                issues.append(venue + ":PRIMARY_EXCHANGE_UNAVAILABLE")
                continue
        passed = inspect(venue, pair, 3)
        if passed:
            primary_good.append(passed)

    result["primary_venues_corrob"] = len(primary_good)
    primary_rule = len(primary_good) >= 2

    # Smaller venues are checked only AFTER all three primary venues. They
    # supply 500-bar research EMA data when the primary pair coverage is short.
    # Otherwise they can provide corroboration, but never override an observed
    # failure of the primary-source policy without a distinct review status.
    for venue, pair in fallback:
        passed = inspect(venue, pair, 500)
        if passed:
            fallback_good.append(passed)
        if primary_rule and fallback_good:
            break  # one corroborated 500-bar EMA source is sufficient

    result["sources_corrob"] = len(primary_good) + len(fallback_good)
    result["source_disagreements"] = len(bad)
    if primary_rule:
        result.update(corroboration_status="PRICE_CORROBORATED_PRIMARY_TWO",
                      reason="Two of Coinbase/Kraken/Binance pass 2% exact-day close policy; "
                             "third-source price disagreements retained as evidence.")
        if not fallback_good:
            result.update(ema_status="NOT_EVALUATED",
                          reason=result["reason"] + " No corroborated 500-bar EMA source.")
            return result, audit, None
        selected = fallback_good[0]
    else:
        # The stricter old fail-closed rule remains in force for secondary
        # validation. Two source checks must pass to call this multi-source.
        if bad:
            result.update(corroboration_status="PRICE_CONFLICT_REVIEW",
                          reason="Source discrepancy before two-primary confirmation: " + ";".join(bad))
            return result, audit, None
        required_good = 2 if int(item.get("source_count") or 0) >= 2 else 1
        if result["sources_corrob"] < required_good or not fallback_good:
            result.update(corroboration_status="INSUFFICIENT_CORROBORATION",
                          reason=f"{result['sources_corrob']}/{required_good} agreeing venues; "
                                 + ";".join(issues))
            return result, audit, None
        result.update(corroboration_status=("PRICE_CORROBORATED_FALLBACK_MULTI_SOURCE"
                                          if required_good == 2 else "PRICE_CORROBORATED_FALLBACK_SINGLE_SOURCE"),
                      reason="Primary three checked first; fallback comparison passed. "
                             "Canonical identity and liquidity remain unverified.")
        selected = fallback_good[0]

    technicals = provisional_technicals(selected[2])
    result.update(ema_status=technicals["provisional_technical_status"],
                  ema50=technicals["provisional_ema50"],
                  ema100=technicals["provisional_ema100"],
                  ema200=technicals["provisional_ema200"])
    return result, audit, selected

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
               "statuses": counts, "source_checks": len(audit_rows),
               "primary_order": list(PRIMARY),
               "primary_two_confirmed": sum(r["primary_venues_corrob"] >= 2 for r in report_rows), "fully_verified": 0,
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
