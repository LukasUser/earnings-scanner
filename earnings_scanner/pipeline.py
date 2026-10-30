from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import anthropic

from . import mailer, yahoo
from .brief import Briefer
from .config import Config
from .db import OVERVIEW, Database
from .facts import build_facts
from .nasdaq import NasdaqClient
from .news import NewsClient
from .report import build, render
from .sec import SecClient
from .util import previous_weekday, weekdays_after

log = logging.getLogger(__name__)


def fetch_calendars(cfg: Config, db: Database, nasdaq: NasdaqClient, run_date: date) -> date | None:
    """Store today's, the upcoming, and the previous session's calendars. Returns the previous session date."""
    days = [run_date, *weekdays_after(run_date, cfg.get("calendar", "lookahead_days", 5))]
    previous = None
    if cfg.get("calendar", "include_previous_day", True):
        # Walk back past market holidays (empty calendars) for up to a week.
        d = run_date
        for _ in range(5):
            d = previous_weekday(d)
            try:
                rows = nasdaq.earnings_calendar(d)
            except Exception as e:
                log.warning("calendar %s (previous session) failed: %s", d, e)
                break
            if rows:
                db.upsert_calendar(rows)
                previous = d
                log.info("calendar %s (previous session): %d rows", d, len(rows))
                break
    for d in days:
        try:
            rows = nasdaq.earnings_calendar(d)
        except Exception as e:
            if d == run_date:
                raise
            log.warning("calendar %s failed: %s", d, e)
            continue
        db.upsert_calendar(rows)
        log.info("calendar %s: %d rows", d, len(rows))
    return previous


def select_targets(cfg: Config, db: Database, run_date: date, symbols: list[str] | None, limit: int | None) -> list[dict]:
    dates = [run_date]
    if cfg.get("enrich", "include_next_day", False):
        dates += weekdays_after(run_date, 1)
    rows = [r for d in dates for r in db.calendar(d.isoformat())]
    if symbols:
        wanted = {s.upper() for s in symbols}
        rows = [r for r in rows if r["symbol"] in wanted]
    else:
        min_cap = cfg.get("enrich", "min_market_cap", 0)
        rows = [r for r in rows if (r["market_cap"] or 0) >= min_cap]
    rows.sort(key=lambda r: r["market_cap"] or 0, reverse=True)
    return rows[: limit or cfg.get("enrich", "max_companies", 150)]


def research_company(cfg: Config, cal: dict, nasdaq: NasdaqClient, sec: SecClient, news: NewsClient) -> dict:
    symbol = cal["symbol"]
    report_date = date.fromisoformat(cal["report_date"])
    out = {"nasdaq": nasdaq.company(symbol)}
    try:
        out["yahoo"] = yahoo.collect(symbol, report_date, cal["time_of_day"])
    except Exception as e:
        out["yahoo"] = {"errors": {"collect": str(e)}}
    try:
        out["sec"] = sec.recent_filings(symbol, cfg.get("enrich", "sec_filing_days", 45))
    except Exception as e:
        out["sec"] = {"error": str(e)}
    out["news"] = news.headlines(symbol, cal["name"], days=cfg.get("enrich", "news_days", 7))
    out["facts"] = build_facts(cal, out["nasdaq"], out["yahoo"], out["sec"], out["news"])
    return out


def overview_row(f: dict, brief: dict | None) -> dict:
    keys = [
        "symbol", "name", "sector", "time_of_day", "market_cap", "eps_forecast", "eps_revisions_up_4w",
        "eps_revisions_down_4w", "implied_move", "avg_abs_earnings_move", "short_pct_float", "ret_1m",
        "target_upside", "analyst_rating", "insider_sales_90d", "news_count",
    ]
    row = {k: f.get(k) for k in keys}
    row["notable_8k"] = [x["items"] for x in f.get("notable_8k") or []]
    if brief and "error" not in brief:
        row["brief"] = {k: brief[k] for k in ("one_line", "sentiment", "expectations_bar")}
    else:
        row["top_headlines"] = [h["title"] for h in (f.get("headlines") or [])[:3]]
    return row


def run_briefs(cfg: Config, db: Database, run_date: str, all_facts: dict[str, dict]) -> int:
    if not cfg.get("brief", "enabled", True):
        return 0
    if not cfg.anthropic_api_key:
        log.info("ANTHROPIC_API_KEY not set; skipping AI briefs")
        return 0
    model = cfg.get("brief", "model", "claude-opus-5-5")
    briefer = Briefer(model, cfg.get("brief", "effort", "medium"))
    min_cap = cfg.get("brief", "min_market_cap", 0)
    targets = [f for f in all_facts.values() if (f.get("market_cap") or 0) >= min_cap]
    targets.sort(key=lambda f: f.get("market_cap") or 0, reverse=True)
    max_briefs = cfg.get("brief", "max_briefs", 40)
    if len(targets) > max_briefs:
        log.info("capping briefs at %d of %d eligible companies", max_briefs, len(targets))
        targets = targets[:max_briefs]
    log.info("writing %d AI briefs with %s", len(targets), model)

    done = 0
    with ThreadPoolExecutor(max_workers=cfg.get("brief", "workers", 3)) as pool:
        futures = {pool.submit(briefer.company_brief, f): f["symbol"] for f in targets}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                db.save_brief(run_date, sym, model, fut.result())
                done += 1
            except anthropic.AuthenticationError:
                log.error("Anthropic API key rejected; cancelling remaining briefs")
                pool.shutdown(cancel_futures=True)
                return done
            except Exception as e:
                log.warning("brief %s failed: %s", sym, e)
                db.save_brief(run_date, sym, model, {"error": str(e)})

    if cfg.get("brief", "overview", True) and all_facts:
        briefs = db.briefs(run_date)
        rows = [overview_row(f, briefs.get(s)) for s, f in all_facts.items()]
        rows.sort(key=lambda r: r["market_cap"] or 0, reverse=True)
        try:
            db.save_brief(run_date, OVERVIEW, model, briefer.overview(run_date, rows))
        except Exception as e:
            log.warning("overview failed: %s", e)

    log.info("Claude usage: %d input / %d output tokens", briefer.input_tokens, briefer.output_tokens)
    return done


def email_enabled(cfg: Config) -> bool:
    if not cfg.get("email", "enabled", True):
        return False
    if missing := mailer.missing_settings(cfg):
        log.warning("email skipped: set %s in .env", ", ".join(missing))
        return False
    return True


def email_report(cfg: Config, db: Database, run_date: str, previous_date: str | None) -> bool:
    if not email_enabled(cfg):
        return False
    overview = db.briefs(run_date).get(OVERVIEW) or {}
    standouts = [s["symbol"] for s in (overview.get("top_setups") or [])[:3]]
    subject = f"Earnings {run_date}: {len(db.calendar(run_date))} reporting"
    if standouts:
        subject += f" · {', '.join(standouts)} stand out"
    digest = build(db, run_date, previous_date, digest=True, digest_rows=cfg.get("email", "digest_rows", 60))
    try:
        mailer.send_report(cfg, run_date, subject, digest, build(db, run_date, previous_date))
        return True
    except Exception as e:
        log.error("email failed: %s", e)
        return False


def run(
    cfg: Config,
    run_date: date,
    *,
    brief: bool = True,
    email: bool = True,
    symbols: list[str] | None = None,
    limit: int | None = None,
) -> Path:
    db = Database(cfg.db_path)
    run_id = db.start_run(run_date.isoformat())
    try:
        nasdaq = NasdaqClient()
        previous = fetch_calendars(cfg, db, nasdaq, run_date)

        targets = select_targets(cfg, db, run_date, symbols, limit)
        log.info("researching %d companies", len(targets))
        sec = SecClient(cfg.sec_user_agent, cfg.cache_dir)
        news = NewsClient()
        rd = run_date.isoformat()
        all_facts: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=cfg.get("enrich", "workers", 4)) as pool:
            futures = {pool.submit(research_company, cfg, cal, nasdaq, sec, news): cal for cal in targets}
            for i, fut in enumerate(as_completed(futures), 1):
                sym = futures[fut]["symbol"]
                try:
                    res = fut.result()
                except Exception as e:
                    log.warning("[%d/%d] %s failed: %s", i, len(targets), sym, e)
                    continue
                # All DB writes happen on this thread.
                for source in ("nasdaq", "yahoo", "sec"):
                    db.save_snapshot(rd, sym, source, res[source])
                db.save_news(sym, res["news"])
                db.save_filings(sym, res["sec"].get("cik"), res["sec"].get("filings") or [])
                db.save_facts(rd, sym, res["facts"])
                db.commit()
                all_facts[sym] = res["facts"]
                log.info("[%d/%d] %s done", i, len(targets), sym)

        n_briefs = run_briefs(cfg, db, rd, all_facts) if brief else 0
        previous_date = previous.isoformat() if previous else None
        path = render(db, rd, previous_date, cfg.reports_dir)
        log.info("report written to %s", path)
        if email:
            email_report(cfg, db, rd, previous_date)
        db.finish_run(run_id, "ok", companies=len(all_facts), briefs=n_briefs, report_path=str(path))
        return path
    except Exception as e:
        db.finish_run(run_id, "error", error=repr(e))
        if email and email_enabled(cfg):
            try:
                mailer.send_failure(cfg, run_date.isoformat(), repr(e))
            except Exception as mail_err:
                log.error("failure email also failed: %s", mail_err)
        raise
    finally:
        db.close()
