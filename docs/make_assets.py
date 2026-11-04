"""Regenerate the README banner from a real run stored in data/earnings.db.

    .venv/bin/python docs/make_assets.py --date 2026-11-02

Writes docs/assets/banner-{light,dark}.svg. The right side replays that morning: the largest
companies fill in one by one (options-implied move vs. average past move), then Claude's briefs,
then the email, with the overview's standout setups lit up.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from earnings_scanner.config import load_config  # noqa: E402
from earnings_scanner.db import OVERVIEW, Database  # noqa: E402

OUT = ROOT / "docs" / "assets"
FONT = 'system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'
LOOP = 14  # seconds
ROWS = 8

THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781", axis="#c3c2b7",
                  past="#2a78d6", implied="#eb6834", star="#1baf7a", tape="#f2f1ec", border="#e1e0d9"),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781", axis="#383835",
                 past="#3987e5", implied="#d95926", star="#199e70", tape="#232321", border="#2c2c2a"),
}


def banner(t: dict, rows: list[dict], standouts: list[str], day: date, n_calendar: int, n_researched: int, n_briefs: int) -> str:
    w, h = 1280, 360
    center, gap, row_h, top = 1011, 36, 28, 72
    scale = 150 / max(max(r["implied_move"], r["avg_abs_earnings_move"]) for r in rows)

    # Timeline as % of the loop: calendar, research (rows fill in), briefs (standouts light up), email.
    research_at, briefs_at, email_at, reset_at = 7, 52, 70, 96
    fill = (briefs_at - research_at - 3) / len(rows)
    keyframes, parts = [], []

    def keyframe(name: str, start: float, frm: str, to: str) -> None:
        # Hold `frm` until `start`, ease to `to`, hold through the loop, then snap back. Elements rest at `to`,
        # so a viewer with reduced motion sees the finished state.
        keyframes.append(
            f"@keyframes {name}{{0%,{start:.1f}%{{{frm}}}{start + 2.5:.1f}%,{reset_at}%{{{to}}}100%{{{frm}}}}}"
        )

    for i, r in enumerate(rows):
        y = top + i * row_h
        start = research_at + i * fill
        past_w, implied_w = r["avg_abs_earnings_move"] * scale, r["implied_move"] * scale
        keyframe(f"g{i}", start, "transform:scaleX(0)", "transform:scaleX(1)")
        keyframe(f"v{i}", start + 1.5, "opacity:0", "opacity:1")
        grow = f"transform-box:fill-box;animation:g{i} {LOOP}s linear infinite"
        fade = f"animation:v{i} {LOOP}s linear infinite"
        parts += [
            f'<rect x="{center - gap - past_w:.1f}" y="{y}" width="{past_w:.1f}" height="14" rx="2" fill="{t["past"]}" style="transform-origin:right center;{grow}"/>',
            f'<rect x="{center + gap}" y="{y}" width="{implied_w:.1f}" height="14" rx="2" fill="{t["implied"]}" style="transform-origin:left center;{grow}"/>',
            f'<text x="{center - gap - past_w - 7:.1f}" y="{y + 11.5}" text-anchor="end" class="px" fill="{t["ink2"]}" style="{fade}">{r["avg_abs_earnings_move"] * 100:.1f}%</text>',
            f'<text x="{center + gap + implied_w + 7:.1f}" y="{y + 11.5}" class="px" fill="{t["ink2"]}" style="{fade}">{r["implied_move"] * 100:.1f}%</text>',
            f'<text x="{center}" y="{y + 11.5}" text-anchor="middle" class="sym" fill="{t["ink"]}">{escape(r["symbol"])}</text>',
        ]
        if r["symbol"] in standouts:
            lit = briefs_at + 2 + standouts.index(r["symbol"]) * 4
            keyframe(f"s{i}", lit, "opacity:0", "opacity:1")
            star = f"animation:s{i} {LOOP}s linear infinite"
            parts += [
                f'<rect x="{center - 30}" y="{y - 2}" width="60" height="18" rx="9" fill="{t["star"]}" style="{star}"/>',
                f'<text x="{center}" y="{y + 11.5}" text-anchor="middle" class="sym" fill="#ffffff" style="{star}">{escape(r["symbol"])}</text>',
            ]

    # Status line: one text per stage, each visible only during its stage. The last stage rests visible.
    stages = [
        (0, research_at, f"{day:%b %-d %Y}  ·  {n_calendar} companies on Nasdaq's calendar"),
        (research_at, briefs_at, f"Researching {n_researched} companies, largest first"),
        (briefs_at, email_at, f"Claude writing {n_briefs} one-sentence briefs"),
        (email_at, 100, f"Emailed  ·  {', '.join(standouts)} stand out"),
    ]
    status = []
    for k, (a, b, label) in enumerate(stages):
        last = k == len(stages) - 1
        keyframes.append(
            f"@keyframes t{k}{{0%,{max(a - 0.01, 0):.2f}%{{opacity:0}}{a}%,{b - 0.01:.2f}%{{opacity:1}}"
            + ("100%{opacity:1}}" if last else f"{b}%,100%{{opacity:0}}}}")
        )
        rest = "" if last else "opacity:0;"
        status.append(
            f'<text x="790" y="34" class="status" fill="{t["ink2"]}" style="{rest}animation:t{k} {LOOP}s linear infinite">{escape(label)}</text>'
        )

    legend = (
        f'<rect x="{center - gap - 10}" y="50" width="10" height="10" rx="2" fill="{t["past"]}"/>'
        f'<text x="{center - gap - 16}" y="59.5" text-anchor="end" class="legend" fill="{t["muted"]}">average past move</text>'
        f'<rect x="{center + gap}" y="50" width="10" height="10" rx="2" fill="{t["implied"]}"/>'
        f'<text x="{center + gap + 16}" y="59.5" class="legend" fill="{t["muted"]}">options imply today</text>'
    )

    chips, cx = [], 56
    for label in ("Nasdaq", "Yahoo Finance", "SEC EDGAR", "News RSS", "Claude"):
        cw = len(label) * 8.2 + 26
        chips.append(
            f'<rect x="{cx}" y="248" width="{cw:.0f}" height="30" rx="15" fill="none" stroke="{t["axis"]}"/>'
            f'<text x="{cx + cw / 2:.0f}" y="268" text-anchor="middle" class="chip">{label}</text>'
        )
        cx += cw + 10

    # Ticker tape: two identical copies side by side, scrolled by exactly one copy width so the loop is
    # seamless. textLength pins each copy's rendered width, since SVG can't measure text.
    gap_text = "    •    "
    items = [f"{n_calendar} companies on the calendar", f"{n_researched} researched", f"{n_briefs} one-sentence briefs",
             "4 free data sources", "1 email before the open"]
    item_text = gap_text.join(items) + gap_text
    while len(item_text) * 7.1 < w + 40:
        item_text += item_text
    copy_w = round(len(item_text) * 7.1)
    tape = "".join(
        f'<text x="{k * copy_w}" y="339" class="tape" textLength="{copy_w}" lengthAdjust="spacing" xml:space="preserve">{escape(item_text)}</text>'
        for k in (0, 1)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="earnings-scanner: the day's biggest earnings reports, researched and briefed by Claude, in your inbox before the open">
<style>
  text {{ font-family: {FONT}; }}
  .eyebrow {{ font-size: 14px; font-weight: 600; letter-spacing: 2.4px; fill: {t["muted"]}; }}
  .title {{ font-size: 66px; font-weight: 700; letter-spacing: -1.5px; fill: {t["ink"]}; }}
  .tag {{ font-size: 22px; fill: {t["ink2"]}; }}
  .chip {{ font-size: 14px; font-weight: 500; fill: {t["ink2"]}; }}
  .tape {{ font-size: 15px; font-weight: 500; fill: {t["ink2"]}; font-variant-numeric: tabular-nums; }}
  .px {{ font-size: 11.5px; font-variant-numeric: tabular-nums; }}
  .sym {{ font-size: 12px; font-weight: 700; }}
  .legend {{ font-size: 11.5px; }}
  .status {{ font-size: 13px; font-weight: 600; }}
  .scroll {{ animation: scroll {copy_w / 34:.0f}s linear infinite; }}
  @keyframes scroll {{ to {{ transform: translateX(-{copy_w}px); }} }}
  {"".join(keyframes)}
  @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}
</style>
<defs><clipPath id="card"><rect width="{w}" height="{h}" rx="16"/></clipPath></defs>
<g clip-path="url(#card)">
  <rect width="{w}" height="{h}" fill="{t["surface"]}"/>
  {"".join(status)}
  {legend}
  {"".join(parts)}
  <text x="56" y="84" class="eyebrow">WEEKDAYS 07:00  ·  PYTHON  ·  CLAUDE</text>
  <text x="52" y="156" class="title">earnings-scanner</text>
  <text x="56" y="203" class="tag">The day's biggest earnings reports, researched</text>
  <text x="56" y="231" class="tag">and briefed in your inbox before the open.</text>
  {"".join(chips)}
  <rect y="306" width="{w}" height="54" fill="{t["tape"]}"/>
  <g class="scroll">{tape}</g>
</g>
<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="16" fill="none" stroke="{t["border"]}"/>
</svg>
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help="run date to draw from (YYYY-MM-DD)")
    args = p.parse_args()

    db = Database(load_config().db_path)
    facts, briefs = db.facts(args.date), db.briefs(args.date)
    usable = {s: f for s, f in facts.items() if f.get("implied_move") and f.get("avg_abs_earnings_move")}
    standouts = [s["symbol"] for s in briefs[OVERVIEW]["top_setups"] if s["symbol"] in usable][:3]
    # The standouts, then the largest of the rest, shown largest first.
    largest = sorted(usable.values(), key=lambda f: -(f.get("market_cap") or 0))
    others = [f for f in largest if f["symbol"] not in standouts][: ROWS - len(standouts)]
    rows = sorted([usable[s] for s in standouts] + others, key=lambda f: -(f.get("market_cap") or 0))
    n_briefs = len([b for b in briefs if b != OVERVIEW])

    OUT.mkdir(parents=True, exist_ok=True)
    for mode, t in THEMES.items():
        svg = banner(t, rows, standouts, date.fromisoformat(args.date), len(db.calendar(args.date)), len(facts), n_briefs)
        (OUT / f"banner-{mode}.svg").write_text(svg)
    print("rows:", [r["symbol"] for r in rows], "| standouts:", standouts)


if __name__ == "__main__":
    main()
