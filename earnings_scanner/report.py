"""Render the daily Markdown report (and a short email digest) from what's stored in the database."""

from __future__ import annotations

from pathlib import Path

from .db import OVERVIEW, Database
from .util import fmt_money, fmt_num, fmt_pct

TIME_LABEL = {"pre-market": "BMO", "after-hours": "AMC", "not-supplied": "?"}


def _ratio(v: float | None) -> str:
    return "–" if v is None else f"{v:.2f}"


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _surprise(actual: float, estimate: float) -> str:
    # A % of a tiny or negative estimate isn't meaningful (a -$0.23 estimate beaten by $2.86 is "+1243%").
    if estimate < 0.10:
        return "n/m"
    return f"{(actual - estimate) / estimate * 100:+.1f}%"


def build(
    db: Database, run_date: str, previous_date: str | None, *, digest: bool = False, digest_rows: int = 60,
    note: str | None = None,
) -> str:
    """The full report, or with digest=True a short version for email: overview, briefs and the summary table."""
    facts = db.facts(run_date)
    briefs = db.briefs(run_date)
    calendar = db.calendar(run_date)
    lines: list[str] = [f"# Earnings scanner — {run_date}", ""]
    lines.append(
        f"{len(calendar)} companies on the Nasdaq calendar today; {len(facts)} researched; "
        f"{len([b for b in briefs if b != OVERVIEW])} AI briefs."
    )
    lines.append("")
    if note:
        lines += [f"**Note:** {note}", ""]
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
        reported = [r for r in db.calendar(previous_date) if r["eps_actual"] is not None and r["eps_forecast"] is not None]
        reported.sort(key=lambda r: r["market_cap"] or 0, reverse=True)
        if reported:
            lines += [f"## Last session's results ({previous_date}, largest reporters)", ""]
            lines += ["| | Symbol | Company | Mkt cap | EPS | Est. | Surprise |", "|---|---|---|---|---|---|---|"]
            for r in reported[:12]:
                diff = r["eps_actual"] - r["eps_forecast"]
                label = "In line" if abs(diff) < 0.005 else "Beat" if diff > 0 else "Miss"
                lines.append(
                    f"| {label} | {r['symbol']} | {_cell(r['name'])} | {fmt_money(r['market_cap'])} | "
                    f"{fmt_num(r['eps_actual'])} | {fmt_num(r['eps_forecast'])} | {_surprise(r['eps_actual'], r['eps_forecast'])} |"
                )
            lines += ["", "_Surprise is computed from the EPS and estimate shown; n/m where the estimate is below $0.10 "
                      "or negative. Nasdaq's EPS can be GAAP where the estimate is adjusted, so check big misses._", ""]

    ordered = sorted(facts.values(), key=lambda f: f.get("market_cap") or 0, reverse=True)

    if digest:
        briefed = [f for f in ordered if f["symbol"] in briefs and "error" not in briefs[f["symbol"]]]
        if briefed:
            lines += ["## Briefs", ""]
            for f in briefed:
                b = briefs[f["symbol"]]
                lines.append(
                    f"- **{f['symbol']}** ({TIME_LABEL.get(f['time_of_day'], '?')}, {fmt_money(f.get('market_cap'))}) "
                    f"{b['one_line']} _({b['sentiment']}, bar: {b['expectations_bar']})_"
                )
            lines.append("")

    table = ordered[:digest_rows] if digest else ordered
    if table:
        lines += ["## Today's reporters", ""]
        if len(table) < len(ordered):
            lines += [f"Largest {len(table)} of {len(ordered)}; the attached full report has them all.", ""]
        lines += [
            "| Symbol | When | Mkt cap | EPS est. (#) | Rev. 4w ↑/↓ | Implied move | Avg past move | "
            "Short % float | Rating | Target upside | 1m return | News |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for f in table:
            n_est = f"{int(f['num_estimates'])}" if f.get("num_estimates") else "–"
            sym = f["symbol"] if digest else f"[{f['symbol']}](#{f['symbol'].lower()})"
            lines.append(
                f"| {sym} | {TIME_LABEL.get(f['time_of_day'], '?')} | "
                f"{fmt_money(f.get('market_cap'))} | {fmt_num(f.get('eps_forecast'))} ({n_est}) | "
                f"{f.get('eps_revisions_up_4w') if f.get('eps_revisions_up_4w') is not None else '–'}/"
                f"{f.get('eps_revisions_down_4w') if f.get('eps_revisions_down_4w') is not None else '–'} | "
                f"{fmt_pct(f.get('implied_move'), signed=False)} | {fmt_pct(f.get('avg_abs_earnings_move'), signed=False)} | "
                f"{fmt_pct(f.get('short_pct_float'), signed=False)} | {f.get('analyst_rating') or '–'} | "
                f"{fmt_pct(f.get('target_upside'))} | {fmt_pct(f.get('ret_1m'))} | {f.get('news_count', 0)} |"
            )
        lines.append("")

    if digest:
        if ordered:
            lines.append("_Per-company detail (expectations, price, positioning, analysts, filings, headlines) is in the attached full report._")
        return "\n".join(lines)

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
            # markdown="1" lets the HTML email renderer process the list inside the raw <details> block.
            lines.append('<details markdown="1"><summary>Headlines</summary>')
            lines.append("")
            for h in f["headlines"][:8]:
                when = (h.get("published_at") or "")[:10]
                lines.append(f"- {when} [{h['title']}]({h['url']}) — {h.get('source') or ''}")
            lines += ["", "</details>", ""]

    return "\n".join(lines)


def render(db: Database, run_date: str, previous_date: str | None, out_dir: Path, note: str | None = None) -> Path:
    path = out_dir / f"{run_date}.md"
    path.write_text(build(db, run_date, previous_date, note=note))
    return path
