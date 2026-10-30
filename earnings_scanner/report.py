"""Render the daily Markdown report from what's stored in the database."""

from __future__ import annotations

from pathlib import Path

from .db import OVERVIEW, Database
from .util import fmt_money, fmt_num, fmt_pct

TIME_LABEL = {"pre-market": "BMO", "after-hours": "AMC", "not-supplied": "?"}


def _ratio(v: float | None) -> str:
    return "–" if v is None else f"{v:.2f}"


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render(db: Database, run_date: str, previous_date: str | None, out_dir: Path) -> Path:
    facts = db.facts(run_date)
    briefs = db.briefs(run_date)
    calendar = db.calendar(run_date)
    lines: list[str] = [f"# Earnings scanner — {run_date}", ""]
    lines.append(
        f"{len(calendar)} companies on the Nasdaq calendar today; {len(facts)} researched; "
        f"{len([b for b in briefs if b != OVERVIEW])} AI briefs."
    )
    lines.append("")
    lines.append("> Generated automatically from public data. Not investment advice.")
    lines.append("")

    if ov := briefs.get(OVERVIEW):
        lines += ["## Overview", "", ov["summary"], ""]
        if ov.get("top_setups"):
            lines.append("**Setups that stand out**")
            lines.append("")
            lines += [f"- **{s['symbol']}** — {s['reason']}" for s in ov["top_setups"]]
            lines.append("")

    if previous_date:
        reported = [r for r in db.calendar(previous_date) if r["surprise_pct"] is not None and (r["market_cap"] or 0) >= 1e9]
        if reported:
            reported.sort(key=lambda r: r["surprise_pct"])
            misses, beats = reported[:5], reported[::-1][:5]
            lines += [f"## Last session's results ({previous_date}, market cap ≥ $1B)", ""]
            lines += ["| | Symbol | Company | EPS | Est. | Surprise |", "|---|---|---|---|---|---|"]
            for label, group in (("Beat", beats), ("Miss", misses)):
                for r in group:
                    if (label == "Beat") != (r["surprise_pct"] > 0):
                        continue
                    lines.append(
                        f"| {label} | {r['symbol']} | {_cell(r['name'])} | {fmt_num(r['eps_actual'])} | "
                        f"{fmt_num(r['eps_forecast'])} | {r['surprise_pct']:+.1f}% |"
                    )
            lines.append("")

    ordered = sorted(facts.values(), key=lambda f: f.get("market_cap") or 0, reverse=True)
    if ordered:
        lines += ["## Today's reporters", ""]
        lines += [
            "| Symbol | When | Mkt cap | EPS est. (#) | Rev. 4w ↑/↓ | Implied move | Avg past move | "
            "Short % float | Rating | Target upside | 1m return | News |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for f in ordered:
            n_est = f"{int(f['num_estimates'])}" if f.get("num_estimates") else "–"
            lines.append(
                f"| [{f['symbol']}](#{f['symbol'].lower()}) | {TIME_LABEL.get(f['time_of_day'], '?')} | "
                f"{fmt_money(f.get('market_cap'))} | {fmt_num(f.get('eps_forecast'))} ({n_est}) | "
                f"{f.get('eps_revisions_up_4w') if f.get('eps_revisions_up_4w') is not None else '–'}/"
                f"{f.get('eps_revisions_down_4w') if f.get('eps_revisions_down_4w') is not None else '–'} | "
                f"{fmt_pct(f.get('implied_move'), signed=False)} | {fmt_pct(f.get('avg_abs_earnings_move'), signed=False)} | "
                f"{fmt_pct(f.get('short_pct_float'), signed=False)} | {f.get('analyst_rating') or '–'} | "
                f"{fmt_pct(f.get('target_upside'))} | {fmt_pct(f.get('ret_1m'))} | {f.get('news_count', 0)} |"
            )
        lines.append("")

    for f in ordered:
        sym = f["symbol"]
        lines += [f"### {sym}", ""]
        lines.append(
            f"**{f['name']}** · {f.get('sector') or '–'} / {f.get('industry') or '–'} · "
            f"{fmt_money(f.get('market_cap'))} · reports {f['report_date']} {f['time_of_day']} "
            f"(FQ {f.get('fiscal_quarter') or '–'})"
        )
        lines.append("")
        lines.append(
            f"- **Expectations:** EPS {fmt_num(f.get('eps_forecast'))} "
            f"(range {fmt_num(f.get('eps_low'))}–{fmt_num(f.get('eps_high'))}, last year {fmt_num(f.get('last_year_eps'))}); "
            f"revenue est. {fmt_money((f.get('revenue_estimate') or {}).get('avg'))}; beats in last quarters: {f.get('beats_last_n') or '–'}"
        )
        lines.append(
            f"- **Move:** implied {fmt_pct(f.get('implied_move'), signed=False)} (exp. {f.get('implied_move_expiry') or '–'}) "
            f"vs. avg past {fmt_pct(f.get('avg_abs_earnings_move'), signed=False)}, max {fmt_pct(f.get('max_abs_earnings_move'), signed=False)}; "
            f"put/call OI {_ratio(f.get('put_call_oi_ratio'))}"
        )
        lines.append(
            f"- **Price:** {fmt_num(f.get('price'))}; 5d {fmt_pct(f.get('ret_5d'))}, 1m {fmt_pct(f.get('ret_1m'))}, "
            f"3m {fmt_pct(f.get('ret_3m'))}, 1y {fmt_pct(f.get('ret_1y'))}; {fmt_pct(f.get('pct_from_52w_high'))} from 52w high; "
            f"fwd P/E {fmt_num(f.get('forward_pe'), 1)}"
        )
        lines.append(
            f"- **Positioning:** short {fmt_pct(f.get('short_pct_float'), signed=False)} of float "
            f"({fmt_num(f.get('short_ratio_days'), 1)} days to cover, m/m {fmt_pct(f.get('shares_short_change'))}); "
            f"institutions {fmt_num(f.get('institutional_ownership_pct'), 1)}%; insiders 90d: "
            f"{f.get('insider_buys_90d') or 0} buys / {f.get('insider_sales_90d') or 0} sales "
            f"({fmt_money(f.get('insider_sale_value_90d'))} sold)"
        )
        lines.append(
            f"- **Analysts:** {f.get('analyst_rating') or '–'}, mean target {fmt_num(f.get('price_target_mean'))} "
            f"({fmt_pct(f.get('target_upside'))})"
        )
        for a in (f.get("recent_analyst_actions") or [])[:4]:
            pt = f", PT {a.get('priorPriceTarget') or '–'}→{a.get('currentPriceTarget')}" if a.get("currentPriceTarget") else ""
            lines.append(f"  - {str(a.get('GradeDate'))[:10]} {a.get('Firm')}: {a.get('FromGrade') or '–'}→{a.get('ToGrade')}{pt}")
        for fl in f.get("notable_8k") or []:
            lines.append(f"- **8-K {fl['filed']}:** [{', '.join(fl['items'])}]({fl['url']})")
        lines.append("")

        if b := briefs.get(sym):
            if "error" in b:
                lines += [f"_AI brief failed: {b['error']}_", ""]
            else:
                lines += [
                    f"**Brief:** {b['one_line']} _({b['sentiment']}, bar: {b['expectations_bar']})_",
                    "",
                ]

        if f.get("headlines"):
            lines.append("<details><summary>Headlines</summary>")
            lines.append("")
            for h in f["headlines"][:8]:
                when = (h.get("published_at") or "")[:10]
                lines.append(f"- {when} [{h['title']}]({h['url']}) — {h.get('source') or ''}")
            lines += ["", "</details>", ""]

    path = out_dir / f"{run_date}.md"
    path.write_text("\n".join(lines))
    return path
