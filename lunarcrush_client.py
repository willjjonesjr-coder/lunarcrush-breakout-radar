import os
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any

import requests


class LunarCrushClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://lunarcrush.com/api4",
        rpm: int = 10,
        daily_budget: int = 2000,
        state_file: str = "data/api_usage.json",
    ):
        self.api_key = api_key or os.getenv("LUNARCRUSH_API_KEY")
        if not self.api_key:
            raise RuntimeError("LUNARCRUSH_API_KEY is not set.")

        self.base_url = base_url.rstrip("/")
        self.min_interval = 60.0 / max(1, rpm)
        self.daily_budget = daily_budget
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0

    def _load_state(self):
        if not self.state_file.exists():
            return {"date_utc": "", "requests": 0}
        try:
            return json.loads(self.state_file.read_text())
        except Exception:
            return {"date_utc": "", "requests": 0}

    def _save_state(self, state):
        self.state_file.write_text(json.dumps(state))

    def _budget_check(self):
        state = self._load_state()
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if state.get("date_utc") != today:
            state = {"date_utc": today, "requests": 0}
        if state["requests"] >= self.daily_budget:
            raise RuntimeError(
                f"Daily API budget reached ({self.daily_budget})."
            )
        self._save_state(state)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None):
        self._budget_check()

        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        response = requests.get(url, headers=headers, params=params, timeout=45)
        self._last_request = time.monotonic()

        state = self._load_state()
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if state.get("date_utc") != today:
            state = {"date_utc": today, "requests": 0}
        state["requests"] += 1
        self._save_state(state)

        if response.status_code == 429:
            raise RuntimeError("LunarCrush rate limit (429). Try again later.")
        if response.status_code == 402:
            raise RuntimeError(
                f"LunarCrush endpoint is gated for this plan: {url}"
            )
        response.raise_for_status()

        return response.json()
