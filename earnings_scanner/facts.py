"""Condense the raw per-source payloads into one flat set of decision-relevant facts."""

from __future__ import annotations

from typing import Any

from .util import dig, parse_number


def _rows(obj: Any, *path: str) -> list[dict]:
    rows = dig(obj, *path)
    return rows if isinstance(rows, list) else []


def nasdaq_facts(n: dict) -> dict:
    summary = {k: dig(v, "value") for k, v in (dig(n, "summary", "summaryData") or {}).items()}
    q_fc = (_rows(n, "eps_forecast", "quarterlyForecast", "rows") or [{}])[0]
    y_fc = (_rows(n, "eps_forecast", "yearlyForecast", "rows") or [{}])[0]
    target = dig(n, "price_target", "consensusOverview") or {}
    inst = dig(n, "institutional") or {}
    active = {r.get("positions"): r for r in _rows(inst, "activePositions", "rows")}
    new_sold = {r.get("positions"): r for r in _rows(inst, "newSoldOutPositions", "rows")}
    short_rows = _rows(n, "short_interest", "shortInterestTable", "rows")
    return {
        "price": parse_number(dig(n, "quote", "primaryData", "lastSalePrice")),
        "price_change_pct": parse_number(dig(n, "quote", "primaryData", "percentageChange")),
        "market_status": dig(n, "quote", "marketStatus"),
        "exchange": summary.get("Exchange"),
        "sector": summary.get("Sector"),
        "industry": summary.get("Industry"),
        "one_year_target": parse_number(summary.get("OneYrTarget")),
        "average_volume": parse_number(summary.get("AverageVolume")),
        "description": dig(n, "profile", "CompanyDescription", "value"),
        "q_eps_consensus": q_fc.get("consensusEPSForecast"),
        "q_eps_high": q_fc.get("highEPSForecast"),
        "q_eps_low": q_fc.get("lowEPSForecast"),
        "q_eps_revisions_up_4w": q_fc.get("up"),
        "q_eps_revisions_down_4w": q_fc.get("down"),
        "fy_eps_consensus": y_fc.get("consensusEPSForecast"),
        "fy_fiscal_end": y_fc.get("fiscalEnd"),
        "eps_surprise_history": _rows(n, "eps_surprise", "earningsSurpriseTable", "rows")[:4],
        "analyst_mean_rating": dig(n, "ratings", "meanRatingType"),
        "analyst_counts": {k: target.get(k) for k in ("buy", "hold", "sell")} if target else None,
        "price_target_mean": target.get("priceTarget"),
        "price_target_low": target.get("lowPriceTarget"),
        "price_target_high": target.get("highPriceTarget"),
        "institutional_ownership_pct": parse_number(dig(inst, "ownershipSummary", "SharesOutstandingPCT", "value")),
        "institutions_increased": parse_number(dig(active, "Increased Positions", "holders")),
        "institutions_decreased": parse_number(dig(active, "Decreased Positions", "holders")),
        "institutions_new": parse_number(dig(new_sold, "New Positions", "holders")),
        "institutions_sold_out": parse_number(dig(new_sold, "Sold Out Positions", "holders")),
        "short_interest": [
            {
                "date": r.get("settlementDate"),
                "shares": parse_number(r.get("interest")),
                "days_to_cover": r.get("daysToCover"),
            }
            for r in short_rows[:3]
        ],
    }


def build_facts(cal: dict, nasdaq: dict, yahoo: dict, sec: dict, news: list[dict]) -> dict:
    nf = nasdaq_facts(nasdaq)
    info = yahoo.get("info") or {}
    price = yahoo.get("price") or {}
    reactions = yahoo.get("earnings_reactions") or {}
    implied = yahoo.get("implied_move") or {}
    est = yahoo.get("estimates") or {}
    insiders = yahoo.get("insiders") or {}
    spot = price.get("last_close") or nf["price"]
    target_mean = nf["price_target_mean"] or info.get("targetMeanPrice")

    filings = sec.get("filings") or []
    notable = [f for f in filings if f["form"] in ("8-K", "8-K/A") and set(f["items"]) - {"9.01", "2.02", "7.01"}]

    return {
        "symbol": cal["symbol"],
        "name": cal["name"],
        "report_date": cal["report_date"],
        "time_of_day": cal["time_of_day"],
        "fiscal_quarter": cal["fiscal_quarter"],
        "market_cap": cal["market_cap"] or info.get("marketCap"),
        "sector": nf["sector"] or info.get("sector"),
        "industry": nf["industry"] or info.get("industry"),
        "description": (nf["description"] or "")[:800],
        # Expectations
        "eps_forecast": cal["eps_forecast"],
        "num_estimates": cal["num_estimates"],
        "last_year_eps": cal["last_year_eps"],
        "eps_high": nf["q_eps_high"],
        "eps_low": nf["q_eps_low"],
        "eps_revisions_up_4w": nf["q_eps_revisions_up_4w"],
        "eps_revisions_down_4w": nf["q_eps_revisions_down_4w"],
        "eps_trend": est.get("eps_trend"),
        "revenue_estimate": est.get("revenue_estimate"),
        "eps_surprise_history": nf["eps_surprise_history"],
        # Price action / valuation
        "price": spot,
        "ret_5d": price.get("ret_5d"),
        "ret_1m": price.get("ret_1m"),
        "ret_3m": price.get("ret_3m"),
        "ret_1y": price.get("ret_1y"),
        "pct_from_52w_high": price.get("pct_from_52w_high"),
        "realized_vol_20d": price.get("realized_vol_20d"),
        "forward_pe": info.get("forwardPE"),
        "trailing_pe": info.get("trailingPE"),
        "ev_to_ebitda": info.get("enterpriseToEbitda"),
        "revenue_growth": info.get("revenueGrowth"),
        "profit_margin": info.get("profitMargins"),
        "beta": info.get("beta"),
        # Expected move
        "implied_move": implied.get("implied_move"),
        "implied_move_expiry": implied.get("expiry"),
        "put_call_oi_ratio": implied.get("put_call_oi_ratio"),
        "atm_iv": implied.get("atm_call_iv"),
        "avg_abs_earnings_move": reactions.get("avg_abs_move"),
        "max_abs_earnings_move": reactions.get("max_abs_move"),
        "earnings_move_history": reactions.get("history"),
        "beats_last_n": f"{reactions.get('beats')}/{reactions.get('count')}" if reactions.get("count") else None,
        # Positioning / sentiment
        "short_pct_float": info.get("shortPercentOfFloat"),
        "short_ratio_days": info.get("shortRatio"),
        "shares_short_change": (
            info["sharesShort"] / info["sharesShortPriorMonth"] - 1
            if info.get("sharesShort") and info.get("sharesShortPriorMonth") else None
        ),
        "nasdaq_short_interest": nf["short_interest"],
        "institutional_ownership_pct": nf["institutional_ownership_pct"],
        "institutions_increased": nf["institutions_increased"],
        "institutions_decreased": nf["institutions_decreased"],
        "institutions_new": nf["institutions_new"],
        "institutions_sold_out": nf["institutions_sold_out"],
        "analyst_rating": nf["analyst_mean_rating"] or info.get("recommendationKey"),
        "analyst_counts": nf["analyst_counts"],
        "price_target_mean": target_mean,
        "target_upside": (target_mean / spot - 1) if target_mean and spot else None,
        "recent_analyst_actions": (yahoo.get("analyst_actions") or [])[:8],
        "insider_buys_90d": insiders.get("buys"),
        "insider_sales_90d": insiders.get("sales"),
        "insider_sale_value_90d": insiders.get("sale_value"),
        "insider_buy_value_90d": insiders.get("buy_value"),
        # Filings & news
        "form4_filings_recent": sec.get("form4_count"),
        "notable_8k": [
            {"filed": f["filed"], "items": f["item_labels"] or f["items"], "url": f["url"]} for f in notable[:5]
        ],
        "news_count": len(news),
        "headlines": [
            {"title": it["title"], "source": it["source"], "published_at": it["published_at"], "url": it["url"]}
            for it in news[:12]
        ],
        "data_errors": {
            "nasdaq": [k for k, v in nasdaq.items() if isinstance(v, dict) and "error" in v],
            "yahoo": list((yahoo.get("errors") or {}).keys()),
            "sec": sec.get("error"),
        },
    }
