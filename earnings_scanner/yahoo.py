"""Yahoo Finance (via yfinance): price action, options-implied move, estimates, analysts, insiders."""

from __future__ import annotations

import bisect
import logging
import warnings
from datetime import date, datetime, timedelta
from typing import Any

import yfinance as yf

from .util import df_records, jsonable

log = logging.getLogger(__name__)

# yfinance triggers pandas deprecation warnings on every call; they're noise here.
warnings.filterwarnings("ignore", module="yfinance")
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

INFO_KEYS = [
    "longName", "sector", "industry", "country", "fullTimeEmployees", "website",
    "currentPrice", "previousClose", "marketCap", "enterpriseValue", "beta",
    "trailingPE", "forwardPE", "pegRatio", "priceToSalesTrailing12Months", "priceToBook",
    "enterpriseToEbitda", "profitMargins", "grossMargins", "operatingMargins",
    "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth", "totalRevenue",
    "totalCash", "totalDebt", "debtToEquity", "freeCashflow", "returnOnEquity",
    "dividendYield", "payoutRatio", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "fiftyDayAverage", "twoHundredDayAverage", "averageVolume", "averageVolume10days",
    "sharesOutstanding", "floatShares", "sharesShort", "sharesShortPriorMonth",
    "shortRatio", "shortPercentOfFloat", "heldPercentInsiders", "heldPercentInstitutions",
    "recommendationKey", "recommendationMean", "numberOfAnalystOpinions",
    "targetMeanPrice", "targetHighPrice", "targetLowPrice",
]


def yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-").replace("/", "-")


def _price_stats(hist) -> dict:
    close = hist["Close"].dropna()
    if close.empty:
        return {}
    last = float(close.iloc[-1])

    def ret(n: int) -> float | None:
        return float(last / close.iloc[-n - 1] - 1) if len(close) > n else None

    daily = close.pct_change().dropna()
    year = close.iloc[-252:]
    vol = hist["Volume"].dropna()
    return {
        "last_close": last,
        "last_close_date": close.index[-1].date().isoformat(),
        "ret_5d": ret(5),
        "ret_1m": ret(21),
        "ret_3m": ret(63),
        "ret_6m": ret(126),
        "ret_1y": ret(252),
        "pct_from_52w_high": float(last / year.max() - 1),
        "pct_from_52w_low": float(last / year.min() - 1),
        "realized_vol_20d": float(daily.iloc[-20:].std() * (252 ** 0.5)) if len(daily) >= 20 else None,
        "avg_volume_20d": float(vol.iloc[-20:].mean()) if len(vol) >= 20 else None,
        "volume_vs_avg_last": float(vol.iloc[-1] / vol.iloc[-21:-1].mean()) if len(vol) >= 21 else None,
    }


def _earnings_reactions(hist, edates, before_date: date, n: int = 8) -> dict:
    """Close-to-close stock move across each past report (BMO: d-1 -> d, AMC: d -> d+1)."""
    close = hist["Close"].dropna()
    days = [ts.date() for ts in close.index]
    moves = []
    for ts, row in edates.iterrows():
        d = ts.date()
        if d >= before_date or row.isna().get("Reported EPS", True):
            continue
        i = bisect.bisect_left(days, d)
        if i >= len(days) or days[i] != d:
            continue
        if ts.hour == 0:  # time unknown: span both sessions
            before, after, timing = i - 1, i + 1, "unknown"
        elif ts.hour < 12:
            before, after, timing = i - 1, i, "pre-market"
        else:
            before, after, timing = i, i + 1, "after-hours"
        if before < 0 or after >= len(days):
            continue
        moves.append({
            "date": d.isoformat(),
            "timing": timing,
            "eps_estimate": jsonable(row.get("EPS Estimate")),
            "eps_reported": jsonable(row.get("Reported EPS")),
            "surprise_pct": jsonable(row.get("Surprise(%)")),
            "move": float(close.iloc[after] / close.iloc[before] - 1),
        })
        if len(moves) >= n:
            break
    abs_moves = [abs(m["move"]) for m in moves]
    return {
        "history": moves,
        "avg_abs_move": sum(abs_moves) / len(abs_moves) if abs_moves else None,
        "max_abs_move": max(abs_moves) if abs_moves else None,
        "beats": sum(1 for m in moves if (m["surprise_pct"] or 0) > 0),
        "count": len(moves),
    }


def _mid(row) -> float | None:
    bid, ask, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
    if bid and ask and bid > 0 and ask > 0:
        return float((bid + ask) / 2)
    return float(last) if last and last > 0 else None


def _implied_move(ticker, spot: float, report_date: date, time_of_day: str) -> dict:
    """ATM straddle on the first expiry that captures the earnings reaction."""
    expiries = ticker.options
    if not expiries:
        return {"error": "no listed options"}
    # An after-hours report on expiry day is only priced into the *next* expiry.
    min_exp = report_date if time_of_day == "pre-market" else report_date + timedelta(days=1)
    exp = next((e for e in expiries if date.fromisoformat(e) >= min_exp), None)
    if exp is None:
        return {"error": "no expiry after report date"}
    chain = ticker.option_chain(exp)
    calls, puts = chain.calls, chain.puts
    if calls.empty or puts.empty:
        return {"error": "empty chain"}
    strike = min(set(calls["strike"]) & set(puts["strike"]), key=lambda k: abs(k - spot))
    call = calls[calls["strike"] == strike].iloc[0]
    put = puts[puts["strike"] == strike].iloc[0]
    c, p = _mid(call), _mid(put)
    if c is None or p is None:
        return {"error": "no usable ATM quotes"}
    straddle = c + p
    put_oi, call_oi = puts["openInterest"].fillna(0).sum(), calls["openInterest"].fillna(0).sum()
    put_vol, call_vol = puts["volume"].fillna(0).sum(), calls["volume"].fillna(0).sum()
    return {
        "expiry": exp,
        "strike": float(strike),
        "straddle": straddle,
        "implied_move": straddle / spot,
        "atm_call_iv": jsonable(call.get("impliedVolatility")),
        "atm_put_iv": jsonable(put.get("impliedVolatility")),
        "put_call_oi_ratio": float(put_oi / call_oi) if call_oi else None,
        "put_call_volume_ratio": float(put_vol / call_vol) if call_vol else None,
    }


def _estimates(t) -> dict:
    out: dict[str, Any] = {}
    for name in ("earnings_estimate", "revenue_estimate", "eps_trend", "eps_revisions"):
        try:
            df = getattr(t, name)
            if df is not None and not df.empty and "0q" in df.index:
                out[name] = jsonable(df.loc["0q"].to_dict())
        except Exception as e:
            out[name] = {"error": str(e)}
    return out


def _analyst_actions(t, days: int = 90) -> list[dict]:
    df = t.upgrades_downgrades
    if df is None or df.empty:
        return []
    cutoff = datetime.now() - timedelta(days=days)
    recent = df[df.index >= cutoff] if df.index.tz is None else df[df.index >= cutoff.astimezone(df.index.tz)]
    return df_records(recent, 15)


def _insiders(t, days: int = 90) -> dict:
    df = t.insider_transactions
    if df is None or df.empty:
        return {"transactions": []}
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent = [r for r in df_records(df) if str(r.get("Start Date") or "")[:10] >= cutoff]
    text = lambda r: (r.get("Text") or "").lower()
    buys = [r for r in recent if "purchase" in text(r) or "buy" in text(r)]
    sales = [r for r in recent if "sale" in text(r)]
    return {
        "buys": len(buys),
        "sales": len(sales),
        "buy_value": sum(r.get("Value") or 0 for r in buys),
        "sale_value": sum(r.get("Value") or 0 for r in sales),
        "transactions": [
            {k: r.get(k) for k in ("Start Date", "Insider", "Position", "Text", "Shares", "Value")}
            for r in recent[:10]
        ],
    }


def collect(symbol: str, report_date: date, time_of_day: str) -> dict:
    t = yf.Ticker(yahoo_symbol(symbol))
    out: dict[str, Any] = {"errors": {}}

    def attempt(name: str, fn):
        try:
            out[name] = fn()
        except Exception as e:
            log.debug("yahoo %s %s failed: %s", symbol, name, e)
            out["errors"][name] = str(e)

    attempt("info", lambda: {k: jsonable(t.info.get(k)) for k in INFO_KEYS})
    hist = None
    try:
        hist = t.history(period="2y", auto_adjust=True)
    except Exception as e:
        out["errors"]["history"] = str(e)
    if hist is not None and not hist.empty:
        attempt("price", lambda: _price_stats(hist))
        attempt("earnings_reactions", lambda: _earnings_reactions(hist, t.get_earnings_dates(limit=16), report_date))
        spot = float(hist["Close"].dropna().iloc[-1])
        attempt("implied_move", lambda: _implied_move(t, spot, report_date, time_of_day))
    attempt("estimates", lambda: _estimates(t))
    attempt("calendar", lambda: jsonable(t.calendar))
    attempt("recommendation_trend", lambda: df_records(t.recommendations, 4))
    attempt("analyst_actions", lambda: _analyst_actions(t))
    attempt("insiders", lambda: _insiders(t))
    return out
