"""Refresh a small number of previously tracked assets for outcome measurement.

No universe rescoring. Never retry a 429. Daily API usage state is shared
with the scanner; reserve quota for other runs. Only request matured horizons.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from lunarcrush_client import LunarCrushClient

ROOT = Path("reports/prospective")
ledger_file = ROOT / "signal_ledger.csv"
diagnostics = json.loads(Path("reports/scan_diagnostics.json").read_text())
cfg = json.loads(Path("config.json").read_text())
result = {"requested": 0, "refreshed": 0, "failed": 0, "rate_limited": False, "skipped": ""}
if diagnostics["history"].get("rate_limited"):
    result["skipped"] = "scanner encountered 429; no additional API requests"
elif not ledger_file.exists():
    result["skipped"] = "no prior ledger"
else:
    ledger = pd.read_csv(ledger_file, dtype={"id": str})
    if ledger.empty:
        result["skipped"] = "empty prior ledger"
    else:
        today = pd.Timestamp.now(tz="UTC").normalize()
        # At least one horizon has matured. Never refresh purely future outcomes.
        pending = ledger[ledger.status.eq("pending")].copy()
        pending["due"] = pd.to_datetime(pending.signal_date_utc, utc=True) + pd.to_timedelta(pending.horizon_days + 1, unit="D")
        due = pending[pending.due < today]
        # Oldest due outcomes first; only assets not already refreshed today.
        ids = due.sort_values("due").id.drop_duplicates().tolist()
        budget = 15  # Maximum additional calls per scan, not an unlimited backlog.
        client = LunarCrushClient(base_url=cfg["base_url"], rpm=cfg["requests_per_minute"], daily_budget=cfg["daily_request_budget"])
        state = client._load_state()
        if state.get("date_utc") == today.date().isoformat():
            budget = min(budget, max(0, cfg["daily_request_budget"] - int(state.get("requests", 0)) - 100))
        for cid in ids[:budget]:
            path = Path("data") / f"history_{cid}.csv"
            if path.exists():
                prior = pd.read_csv(path)
                if "time" in prior and len(prior):
                    last = pd.to_datetime(prior.time, utc=True, errors="coerce").max()
                    if pd.notna(last) and last >= today - pd.Timedelta(days=1):
                        continue
            result["requested"] += 1
            try:
                # Import here to avoid changing scanner execution or scoring.
                from scanner import fetch_history
                hist = fetch_history(client, cid, cfg)
                if hist.empty:
                    result["failed"] += 1
                    continue
                if path.exists():
                    old = pd.read_csv(path)
                    old["time"] = pd.to_datetime(old["time"], utc=True)
                    hist = pd.concat([old, hist], ignore_index=True)
                hist = hist.sort_values("time").drop_duplicates("time", keep="last")
                hist.to_csv(path, index=False)
                result["refreshed"] += 1
            except Exception as exc:
                result["failed"] += 1
                if "rate limit (429)" in str(exc).lower():
                    result["rate_limited"] = True
                    result["skipped"] = "429 circuit breaker"
                    break
                print(f"[WARN] Follow-up history {cid}: {exc}")
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "refresh_diagnostics.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
