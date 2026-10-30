from __future__ import annotations

import math
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def make_session(headers: dict[str, str]) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
    session.mount("https://", adapter)
    session.headers.update(headers)
    return session


class RateLimiter:
    """Spaces calls at least `min_interval` seconds apart across threads."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.min_interval
        if delay > 0:
            time.sleep(delay)


def parse_number(value: Any) -> float | None:
    """Parse Nasdaq-style strings: "$1,234.5", "-$0.12", "($0.12)", "12.5%", "N/A"."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if isinstance(value, float) and math.isnan(value) else float(value)
    s = str(value).strip()
    if not s or s.upper() in {"N/A", "NA", "--", "-"}:
        return None
    negative = s.startswith("-") or "$-" in s or (s.startswith("(") and s.endswith(")"))
    digits = re.sub(r"[^0-9.]", "", s)
    if not digits or digits == ".":
        return None
    try:
        number = float(digits)
    except ValueError:
        return None
    return -number if negative else number


def parse_us_date(value: str | None) -> str | None:
    """"10/31/2025" -> "2025-10-31"."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def dig(obj: Any, *keys: Any) -> Any:
    for key in keys:
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(key)
        elif isinstance(obj, list) and isinstance(key, int):
            obj = obj[key] if -len(obj) <= key < len(obj) else None
        else:
            return None
    return obj


def jsonable(obj: Any) -> Any:
    """Recursively convert pandas/numpy/datetime values into JSON-safe types."""
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):  # includes numpy float64
        return None if math.isnan(obj) or math.isinf(obj) else float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if hasattr(obj, "isoformat"):  # pandas Timestamp
        try:
            return obj.isoformat()
        except ValueError:
            return None
    if hasattr(obj, "item"):  # numpy scalar
        return jsonable(obj.item())
    return str(obj)


def df_records(df: Any, limit: int | None = None) -> list[dict]:
    if df is None or getattr(df, "empty", True):
        return []
    frame = df.reset_index()
    if limit:
        frame = frame.head(limit)
    return jsonable(frame.to_dict("records"))


def weekdays_after(day: date, n: int) -> list[date]:
    out, d = [], day
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def previous_weekday(day: date) -> date:
    d = day - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fmt_money(v: float | None) -> str:
    if v is None:
        return "–"
    a = abs(v)
    sign = "-" if v < 0 else ""
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sign}${a / div:.1f}{suffix}"
    return f"{sign}${a:.2f}"


def fmt_pct(v: float | None, digits: int = 1, signed: bool = True) -> str:
    if v is None:
        return "–"
    return f"{v * 100:+.{digits}f}%" if signed else f"{v * 100:.{digits}f}%"


def fmt_num(v: float | None, digits: int = 2) -> str:
    return "–" if v is None else f"{v:.{digits}f}"
