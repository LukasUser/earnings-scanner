"""Nasdaq.com data via the JSON API that backs https://www.nasdaq.com/market-activity/earnings."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from .util import BROWSER_UA, RateLimiter, make_session, parse_number, parse_us_date

log = logging.getLogger(__name__)

BASE = "https://api.nasdaq.com/api"
HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}

TIME_OF_DAY = {
    "time-pre-market": "pre-market",
    "time-after-hours": "after-hours",
    "time-not-supplied": "not-supplied",
}

# name -> (path template, query params)
COMPANY_ENDPOINTS: dict[str, tuple[str, dict[str, Any]]] = {
    "quote": ("/quote/{s}/info", {"assetclass": "stocks"}),
    "summary": ("/quote/{s}/summary", {"assetclass": "stocks"}),
    "profile": ("/company/{s}/company-profile", {}),
    "eps_forecast": ("/analyst/{s}/earnings-forecast", {}),
    "eps_surprise": ("/company/{s}/earnings-surprise", {}),
    "ratings": ("/analyst/{s}/ratings", {}),
    "price_target": ("/analyst/{s}/targetprice", {}),
    "institutional": (
        "/company/{s}/institutional-holdings",
        {"limit": 10, "type": "TOTAL", "sortColumn": "marketValue"},
    ),
    "short_interest": ("/quote/{s}/short-interest", {"assetClass": "stocks"}),
}


def parse_calendar_row(row: dict, report_date: date) -> dict:
    return {
        "report_date": report_date.isoformat(),
        "symbol": (row.get("symbol") or "").strip().upper(),
        "name": (row.get("name") or "").strip(),
        "time_of_day": TIME_OF_DAY.get(row.get("time") or "", row.get("time") or "not-supplied"),
        "market_cap": parse_number(row.get("marketCap")),
        "fiscal_quarter": row.get("fiscalQuarterEnding"),
        "eps_forecast": parse_number(row.get("epsForecast")),
        "num_estimates": parse_number(row.get("noOfEsts")),
        "last_year_report_date": parse_us_date(row.get("lastYearRptDt")),
        "last_year_eps": parse_number(row.get("lastYearEPS")),
        # Only present once the company has reported.
        "eps_actual": parse_number(row.get("eps")),
        "surprise_pct": parse_number(row.get("surprise")),
        "raw": row,
    }


class NasdaqClient:
    def __init__(self, min_interval: float = 0.3):
        self.session = make_session(HEADERS)
        self.limiter = RateLimiter(min_interval)

    def _get(self, path: str, params: dict | None = None) -> Any:
        self.limiter.wait()
        resp = self.session.get(BASE + path, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("data")

    def earnings_calendar(self, day: date) -> list[dict]:
        data = self._get("/calendar/earnings", {"date": day.isoformat()})
        rows = (data or {}).get("rows") or []
        parsed = [parse_calendar_row(r, day) for r in rows]
        return [r for r in parsed if r["symbol"]]

    def company(self, symbol: str) -> dict[str, Any]:
        """Fetch every per-company endpoint; failures are recorded, not raised."""
        out: dict[str, Any] = {}
        for name, (template, params) in COMPANY_ENDPOINTS.items():
            try:
                out[name] = self._get(template.format(s=symbol), params or None)
            except Exception as e:  # one dead endpoint shouldn't sink the company
                log.debug("nasdaq %s %s failed: %s", symbol, name, e)
                out[name] = {"error": str(e)}
        return out
