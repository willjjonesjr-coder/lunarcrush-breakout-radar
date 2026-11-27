"""Build a research breakout shortlist with optional EMA evidence; do not mutate production or send alerts."""
import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from pathlib import Path

EMA = ("ema50", "ema100", "ema200")
# Same lower bound as the production BREAKOUT / MOMENTUM score band.
MIN_BREAKOUT_SCORE = 55.0
FIELDS = ("research_rank", "coin_id", "symbol", "name", "breakout_score",
          "identity_status", "shortlist_status", "ema_status", "screen_status", "ema_day", "exchange", "pair",
          *EMA, "price_corroboration_status", "market_cap_label",
          "liquidity_label", "confirmation_label", "production_confirmation_blockers",
          "due_diligence_required", "alternate_venue_status", "kraken_usd_spot",
          "alternate_coingecko_id", "alternate_corroborating_venues", "alternate_price_disagreement")


def unique(rows, key):
    indexed = {}
    for row in rows:
        cid = row.get(key, "").strip()
        if not cid.isascii() or not cid.isdecimal() or cid in indexed:
            raise ValueError(f"Missing, invalid, or duplicate {key}: {cid!r}")
        indexed[cid] = row
    return indexed


def number(value):
    try:
        x = float(value)
        return x if isfinite(x) else None
    except (ValueError, TypeError):
        return None


def day(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (dt.astimezone(timezone.utc) if dt.tzinfo else dt).date()
    except (AttributeError, ValueError):
        return None


def identity(row):
    return tuple(" ".join(row.get(k, "").casefold().split()) for k in ("symbol", "name"))


def has_emas(row):
    return all((number(row.get(k)) or 0) > 0 for k in EMA)


def evidence(out, row, outcome, identity_status, history_day, exchange, pair):
    out.update(screen_status=outcome, identity_status=identity_status,
               ema_day=history_day, exchange=exchange, pair=pair,
               **{k: row[k] for k in EMA})


def build(production, inventory, provisional, closed_day, alternate=()):
    current = unique(production, "id")
    verified = unique(inventory["assets"], "coin_id")
    research = unique(provisional, "coin_id")
    alternates = unique(alternate, "coin_id")
    if not current or any(day(r.get("expected_complete_day")) != closed_day for r in current.values()):
        raise ValueError("Production snapshot does not match requested closed UTC day")
    if day(inventory.get("as_of")) != closed_day + timedelta(days=1):
        raise ValueError("Verified inventory does not match requested closed UTC day")

    audit = []
    for cid, row in current.items():
        match, inv = research.get(cid), verified.get(cid)
        score = number(row.get("breakout_score"))
        out = dict.fromkeys(FIELDS, "")
        out.update(coin_id=cid, symbol=row["symbol"], name=row["name"],
                   breakout_score=score if score is not None else "",
                   market_cap_label=row.get("market_cap_label", ""),
                   liquidity_label=row.get("liquidity_label", ""),
                   confirmation_label=row.get("confirmation_label", ""),
                   production_confirmation_blockers=row.get("confirmation_blockers", ""),
                   due_diligence_required="YES", identity_status="UNVERIFIED")
        if match:
            out["price_corroboration_status"] = match.get("price_corroboration_status", "")
        audit.append(out)
        if (row.get("history_selection") != "ANALYZED"
                or row.get("ranking_eligible", "").lower() != "true"):
            out["screen_status"] = "OUTSIDE_ELIGIBLE_COHORT"
        elif score is None or not all(identity(row)) or day(row.get("latest_price_day")) != closed_day:
            out["screen_status"] = "NO_CURRENT_BREAKOUT_SCORE"
        elif (inv and inv.get("selected_in_300") is True
              and inv.get("fresh_300_bar_history") is True
              and day(inv.get("last_completed_candle")) == closed_day
              and row.get("ema_history_source") == "VERIFIED EXCHANGE MAPPING"
              and row.get("technical_status") in {"EMA CONFIRMED", "EMA NOT CONFIRMED"}
              and inv.get("technical_status") == row["technical_status"]
              and inv.get("exchange") and inv.get("pair") and has_emas(row)):
            evidence(out, row, "ALIGNED" if row["technical_status"] == "EMA CONFIRMED" else "NOT_ALIGNED",
                     "VERIFIED", closed_day.isoformat(), inv["exchange"], inv["pair"])
        elif not match:
            out["screen_status"] = "NO_PROVISIONAL_EVIDENCE"
        elif (identity(match) != identity(row)
              or "CONFLICT" in match.get("current_selection_status", "").upper()
              or any(flag in out["price_corroboration_status"].upper()
                     for flag in ("CONFLICT", "MISMATCH", "FAIL"))
              or "CONFLICT" in match.get("refresh_status", "").upper()):
            out.update(screen_status="CONFLICT_REVIEW", identity_status="PROVISIONAL")
        elif (match.get("current_selection_status") != "CURRENT_ANALYZED"
              or match.get("refresh_status") != "REFRESHED_PROVISIONAL"):
            out.update(screen_status="PROVISIONAL_NOT_REFRESHED", identity_status="PROVISIONAL")
        elif day(match.get("history_last_day")) != closed_day:
            out.update(screen_status="STALE_PROVISIONAL", identity_status="PROVISIONAL",
                       ema_day=match.get("history_last_day", ""))
        elif (not has_emas(match) or (number(match.get("history_bars")) or 0) < 300
              or not match.get("exchange") or not match.get("pair")
              or match.get("refreshed_technical_status") not in
                 {"PROVISIONAL EMA ALIGNED", "PROVISIONAL EMA NOT ALIGNED"}):
            out.update(screen_status="INCOMPLETE_PROVISIONAL", identity_status="PROVISIONAL")
        else:
            evidence(out, match, "ALIGNED" if match["refreshed_technical_status"] == "PROVISIONAL EMA ALIGNED"
                     else "NOT_ALIGNED", "PROVISIONAL", closed_day.isoformat(),
                     match["exchange"], match["pair"])

    for out in audit:
        state = out["screen_status"]
        alt = alternates.get(out["coin_id"])
        if (alt and state not in {"OUTSIDE_ELIGIBLE_COHORT", "NO_CURRENT_BREAKOUT_SCORE",
                                 "CONFLICT_REVIEW", "ALIGNED", "NOT_ALIGNED"}
                and out["breakout_score"] >= MIN_BREAKOUT_SCORE):
            out.update(alternate_venue_status=alt.get("status", ""),
                       kraken_usd_spot=alt.get("kraken_usd_spot", ""),
                       alternate_coingecko_id=alt.get("coingecko_id", ""),
                       alternate_corroborating_venues=alt.get("corroborating_venues", ""),
                       alternate_price_disagreement="YES" if alt.get("disagreement") else "")
            if (alt.get("status") == "CORROBORATED" and day(alt.get("closed_day")) == closed_day
                    and identity(alt) == identity(out) and alt.get("coingecko_id")
                    and (number(alt.get("corroborating_venues")) or 0) >= 1
                    and alt.get("exchange") not in {"", None, "kraken"}
                    and str(alt.get("pair", "")).partition("/")[0] == out["symbol"].upper()
                    and has_emas(alt) and alt.get("technical_status") in
                    {"PROVISIONAL EMA ALIGNED", "PROVISIONAL EMA NOT ALIGNED"}):
                state = "ALIGNED" if alt["technical_status"] == "PROVISIONAL EMA ALIGNED" else "NOT_ALIGNED"
                evidence(out, alt, state, "PROVISIONAL", closed_day.isoformat(), alt["exchange"], alt["pair"])
                out["price_corroboration_status"] = "ALTERNATE_VENUE_PRICE_CORROBORATED"
        out["ema_status"] = {
            "ALIGNED": "EMA SUPPORTS BREAKOUT",
            "NOT_ALIGNED": "EMA DOES NOT QUALIFY",
        }.get(state, "EMA NOT EVALUATED")
        if state in {"OUTSIDE_ELIGIBLE_COHORT", "NO_CURRENT_BREAKOUT_SCORE", "CONFLICT_REVIEW"}:
            out["shortlist_status"] = state
        elif out["breakout_score"] < MIN_BREAKOUT_SCORE:
            out["shortlist_status"] = "BELOW_BREAKOUT_SCORE_THRESHOLD"
        else:
            out["shortlist_status"] = "RESEARCH_CANDIDATE"

    shortlist = sorted((o for o in audit if o["shortlist_status"] == "RESEARCH_CANDIDATE"),
                       key=lambda o: (-o["breakout_score"], int(o["coin_id"])))
    for rank, row in enumerate(shortlist, 1):
        row["research_rank"] = rank
    summary = {"closed_utc_day": closed_day.isoformat(), "production_rows": len(current),
               "provisional_rows_outside_snapshot": len(research.keys() - current.keys()),
               "screen_counts": dict(sorted(Counter(o["screen_status"] for o in audit).items())),
               "evaluable_by_identity": dict(sorted(Counter(o["identity_status"] for o in audit
                   if o["screen_status"] in {"ALIGNED", "NOT_ALIGNED"}).items())),
               "shortlist_by_identity": dict(sorted(Counter(o["identity_status"] for o in shortlist).items())),
               "shortlist_by_ema_status": dict(sorted(Counter(o["ema_status"] for o in shortlist).items())),
               "shortlist_status_counts": dict(sorted(Counter(o["shortlist_status"] for o in audit).items())),
               "minimum_breakout_score": MIN_BREAKOUT_SCORE,
               "shortlist_count": len(shortlist),
               "policy": "EMA is supporting evidence only. Research only; no production promotions or alerts."}
    return shortlist, audit, summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--production", required=True, type=Path)
    p.add_argument("--inventory", required=True, type=Path)
    p.add_argument("--provisional", required=True, type=Path)
    p.add_argument("--alternate", type=Path)
    p.add_argument("--closed-day", type=date.fromisoformat,
                   default=datetime.now(timezone.utc).date() - timedelta(days=1))
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    def read_csv(path):
        with path.open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    shortlist, audit, summary = build(read_csv(args.production),
                                      json.loads(args.inventory.read_text(encoding="utf-8")),
                                      read_csv(args.provisional), args.closed_day,
                                      json.loads(args.alternate.read_text()) if args.alternate else ())
    args.output.mkdir(parents=True, exist_ok=True)
    for name, items in (("combined_shortlist.csv", shortlist), ("combined_screen_audit.csv", audit)):
        with (args.output / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(items)
    (args.output / "combined_screen_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

