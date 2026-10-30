"""Recent headlines from Google News and Yahoo Finance RSS feeds."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from .util import BROWSER_UA, RateLimiter, make_session

log = logging.getLogger(__name__)

SUFFIXES = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings?|group|"
    r"sa|ag|nv|se|lp|llc|class [a-c]|common stock|the)\b\.?",
    re.IGNORECASE,
)


def clean_company_name(name: str) -> str:
    cleaned = SUFFIXES.sub("", name.replace(",", " "))
    return re.sub(r"\s+", " ", cleaned).strip(" .&-") or name


def _parse_rss(xml_bytes: bytes, feed: str) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        published = None
        if pub := item.findtext("pubDate"):
            try:
                published = parsedate_to_datetime(pub).astimezone(timezone.utc)
            except (TypeError, ValueError):
                pass
        source_el = item.find("source")
        source = source_el.text if source_el is not None else None
        if feed == "google" and source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        items.append({
            "title": title,
            "url": link,
            "source": source or ("Yahoo Finance" if feed == "yahoo" else None),
            "published_at": published.isoformat() if published else None,
            "feed": feed,
        })
    return items


class NewsClient:
    def __init__(self):
        self.session = make_session({"User-Agent": BROWSER_UA})
        self.limiter = RateLimiter(0.5)

    def _fetch(self, url: str, feed: str) -> list[dict]:
        self.limiter.wait()
        resp = self.session.get(url, timeout=20)
        resp.raise_for_status()
        return _parse_rss(resp.content, feed)

    def headlines(self, symbol: str, name: str, days: int = 7, limit: int = 25) -> list[dict]:
        query = f'"{clean_company_name(name)}" OR "{symbol} stock" when:{days}d'
        sources = [
            (f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en", "google"),
            (f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(symbol)}&region=US&lang=en-US", "yahoo"),
        ]
        items: list[dict] = []
        for url, feed in sources:
            try:
                items.extend(self._fetch(url, feed))
            except Exception as e:
                log.debug("news %s %s failed: %s", symbol, feed, e)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        seen, out = set(), []
        for it in sorted(items, key=lambda x: x["published_at"] or "", reverse=True):
            key = re.sub(r"\W+", "", it["title"].lower())[:80]
            if key in seen:
                continue
            if it["published_at"] and datetime.fromisoformat(it["published_at"]) < cutoff:
                continue
            seen.add(key)
            out.append(it)
        return out[:limit]
