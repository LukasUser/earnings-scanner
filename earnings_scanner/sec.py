"""SEC EDGAR: recent filings (8-K items, Form 4 insider filings, 10-Q/10-K)."""

from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

from .util import RateLimiter, make_session

log = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# 8-K items worth flagging ahead of earnings.
NOTABLE_8K_ITEMS = {
    "1.01": "Material agreement",
    "1.02": "Terminated material agreement",
    "1.05": "Cybersecurity incident",
    "2.01": "Acquisition/disposition completed",
    "2.02": "Results of operations",
    "2.03": "New financial obligation",
    "2.05": "Restructuring / exit costs",
    "2.06": "Material impairment",
    "3.01": "Delisting / listing-rule notice",
    "4.01": "Auditor change",
    "4.02": "Non-reliance on prior financials (restatement)",
    "5.02": "Officer/director change",
    "7.01": "Reg FD disclosure",
    "8.01": "Other events",
}


class SecClient:
    def __init__(self, user_agent: str, cache_dir: Path):
        self.session = make_session({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.limiter = RateLimiter(0.15)  # SEC allows 10 req/s
        self.cache_dir = cache_dir
        self._tickers: dict[str, int] | None = None

    def _get_json(self, url: str) -> dict:
        self.limiter.wait()
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def cik_for(self, symbol: str) -> int | None:
        if self._tickers is None:
            cache = self.cache_dir / "company_tickers.json"
            if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
                raw = json.loads(cache.read_text())
            else:
                raw = self._get_json(TICKERS_URL)
                cache.write_text(json.dumps(raw))
            self._tickers = {v["ticker"].upper(): int(v["cik_str"]) for v in raw.values()}
        sym = symbol.upper()
        return self._tickers.get(sym) or self._tickers.get(sym.replace(".", "-"))

    def recent_filings(self, symbol: str, days: int) -> dict:
        cik = self.cik_for(symbol)
        if cik is None:
            return {"error": "no CIK for symbol"}
        data = self._get_json(SUBMISSIONS_URL.format(cik=cik))
        recent = data.get("filings", {}).get("recent", {})
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        filings = []
        for i, form in enumerate(recent.get("form", [])):
            filed = recent["filingDate"][i]
            if filed < cutoff:
                break  # newest first
            accession = recent["accessionNumber"][i]
            doc = recent["primaryDocument"][i]
            items = [x for x in (recent.get("items", [""] * (i + 1))[i] or "").split(",") if x]
            filings.append({
                "accession": accession,
                "form": form,
                "filed": filed,
                "items": items,
                "item_labels": [NOTABLE_8K_ITEMS[x] for x in items if x in NOTABLE_8K_ITEMS],
                "description": recent.get("primaryDocDescription", [""] * (i + 1))[i],
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{doc}",
            })
        return {
            "cik": cik,
            "sic_description": data.get("sicDescription"),
            "filings": filings,
            "form4_count": sum(1 for f in filings if f["form"] == "4"),
        }
