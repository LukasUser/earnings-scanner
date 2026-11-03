"""Regenerate the README images from a real run stored in data/earnings.db.

    .venv/bin/python docs/make_assets.py --date 2026-11-03 --symbol BKNG

Writes docs/assets/banner-{light,dark}.svg, brief-card-{light,dark}.svg and email.png.
The PNG is a headless Google Chrome screenshot of the email digest.
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import tempfile
import textwrap
from datetime import date
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from earnings_scanner.config import load_config  # noqa: E402
from earnings_scanner.db import Database  # noqa: E402
from earnings_scanner.mailer import CSS as EMAIL_CSS  # noqa: E402
from earnings_scanner.pipeline import email_subject  # noqa: E402
from earnings_scanner.report import TIME_LABEL, build  # noqa: E402

OUT = ROOT / "docs" / "assets"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FONT = 'system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'

THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9",
                  axis="#c3c2b7", up="#2a78d6", down="#e34948", band="#f0efec", tape="#f0efec",
                  border="rgba(11,11,11,0.10)"),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a",
                 axis="#383835", up="#3987e5", down="#e66767", band="#262624", tape="#232321",
                 border="rgba(255,255,255,0.10)"),
}


def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


# ---------------------------------------------------------------- banner

def banner(t: dict, ticker_items: list[str]) -> str:
    w, h = 1280, 360
    # Ticker tape: two identical copies side by side, scrolled by exactly one copy width so the loop is seamless.
    # textLength pins each copy's rendered width, since SVG can't measure text.
    item_text = "    •    ".join(ticker_items) + "    •    "
    copy_w = round(len(item_text) * 7.0)
    while copy_w < w + 40:
        item_text *= 2
        copy_w *= 2
    tape_y = 306

    rnd = random.Random(7)
    closes, price = [], 100.0
    for _ in range(17):
        price *= 1 + rnd.gauss(0.012, 0.03)
        closes.append(price)
    opens = [100.0] + closes[:-1]
    lo = min(min(opens), min(closes)) * 0.97
    hi = max(max(opens), max(closes)) * 1.03
    x0, x1, y0, y1 = 790, 1222, 70, 262

    def py(v: float) -> float:
        return y1 - (v - lo) / (hi - lo) * (y1 - y0)

    step = (x1 - x0) / len(closes)
    candles = []
    for i, (o, c) in enumerate(zip(opens, closes)):
        cx = x0 + step * (i + 0.5)
        wick_hi = max(o, c) * (1 + abs(rnd.gauss(0, 0.012)))
        wick_lo = min(o, c) * (1 - abs(rnd.gauss(0, 0.012)))
        color = t["up"] if c >= o else t["down"]
        top, bottom = py(max(o, c)), py(min(o, c))
        candles.append(
            f'<g class="c" style="animation-delay:{0.15 + i * 0.07:.2f}s">'
            f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{py(wick_hi):.1f}" y2="{py(wick_lo):.1f}" stroke="{color}" stroke-width="2"/>'
            f'<rect x="{cx - 8:.1f}" y="{top:.1f}" width="16" height="{max(bottom - top, 2):.1f}" rx="2" fill="{color}"/></g>'
        )
    last_x, last_y = x0 + step * (len(closes) - 0.5), py(closes[-1])
    gridlines = "".join(
        f'<line x1="{x0 - 10}" x2="{x1 + 10}" y1="{y:.1f}" y2="{y:.1f}" stroke="{t["grid"]}" stroke-width="1"/>'
        for y in (y0 + (y1 - y0) * k / 4 for k in range(5))
    )

    chips, cx = [], 56
    for label in ("Nasdaq", "Yahoo Finance", "SEC EDGAR", "News RSS", "Claude"):
        cw = len(label) * 8.2 + 26
        chips.append(
            f'<rect x="{cx}" y="248" width="{cw:.0f}" height="30" rx="15" fill="none" stroke="{t["axis"]}"/>'
            f'<text x="{cx + cw / 2:.0f}" y="268" text-anchor="middle" class="chip">{label}</text>'
        )
        cx += cw + 10

    tape = "".join(
        f'<text x="{k * copy_w}" y="{tape_y + 33}" class="tape" textLength="{copy_w}" lengthAdjust="spacing">{escape(item_text)}</text>'
        for k in (0, 1)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="earnings-scanner: the day's earnings calendar, researched and briefed by Claude, in your inbox every weekday morning">
<style>
  text {{ font-family: {FONT}; }}
  .eyebrow {{ font-size: 14px; font-weight: 600; letter-spacing: 2.4px; fill: {t["muted"]}; }}
  .title {{ font-size: 66px; font-weight: 700; letter-spacing: -1.5px; fill: {t["ink"]}; }}
  .tag {{ font-size: 22px; fill: {t["ink2"]}; }}
  .chip {{ font-size: 14px; font-weight: 500; fill: {t["ink2"]}; }}
  .tape {{ font-size: 15px; font-weight: 500; fill: {t["ink2"]}; font-variant-numeric: tabular-nums; }}
  .c {{ opacity: 0; animation: rise .5s ease-out forwards; }}
  .scroll {{ animation: scroll {copy_w / 38:.0f}s linear infinite; }}
  .pulse {{ animation: pulse 2s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }}
  @keyframes rise {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: none; }} }}
  @keyframes scroll {{ to {{ transform: translateX(-{copy_w}px); }} }}
  @keyframes pulse {{ 0%, 100% {{ opacity: .9; transform: scale(1); }} 50% {{ opacity: .25; transform: scale(2.2); }} }}
  @media (prefers-reduced-motion: reduce) {{ .c {{ animation: none; opacity: 1; }} .scroll, .pulse {{ animation: none; }} }}
</style>
<defs><clipPath id="card"><rect width="{w}" height="{h}" rx="16"/></clipPath></defs>
<g clip-path="url(#card)">
  <rect width="{w}" height="{h}" fill="{t["surface"]}"/>
  {gridlines}
  {"".join(candles)}
  <circle class="pulse" cx="{last_x:.1f}" cy="{last_y:.1f}" r="6" fill="{t["up"]}"/>
  <text x="56" y="84" class="eyebrow">WEEKDAYS · 07:00 · NASDAQ EARNINGS</text>
  <text x="52" y="160" class="title">earnings-scanner</text>
  <text x="56" y="203" class="tag">The day's earnings calendar, researched and briefed</text>
  <text x="56" y="231" class="tag">by Claude, in your inbox every weekday morning.</text>
  {"".join(chips)}
  <rect y="{tape_y}" width="{w}" height="{h - tape_y}" fill="{t["tape"]}"/>
  <g class="scroll">{tape}</g>
</g>
<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="16" fill="none" stroke="{t["border"]}"/>
</svg>
"""


# ---------------------------------------------------------------- brief card

def brief_card(t: dict, f: dict, b: dict) -> str:
    w, h = 1280, 700
    history = list(reversed(f.get("earnings_move_history") or []))[-8:]  # oldest first
    im = f["implied_move"]
    span = max(im * 1.25, max(abs(r["move"]) for r in history) * 1.2)
    span = (int(span * 100 / 4) + 1) * 0.04  # round up to a 4% tick
    px0, px1, py0, py1 = 130, 1190, 410, 640
    mid = (py0 + py1) / 2

    def y(v: float) -> float:
        return mid - v / span * (py1 - py0) / 2

    ticks = []
    v = -span
    while v <= span + 1e-9:
        yy = y(v)
        ticks.append(
            f'<line x1="{px0}" x2="{px1}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="{t["grid"]}" stroke-width="1"/>'
            f'<text x="{px0 - 14}" y="{yy + 5:.1f}" text-anchor="end" class="axis">{round(v * 100):+d}%</text>'.replace("+0%", "0%")
        )
        v += 0.04
    band = (
        f'<rect x="{px0}" y="{y(im):.1f}" width="{px1 - px0}" height="{y(-im) - y(im):.1f}" fill="{t["band"]}"/>'
        f'<line x1="{px0}" x2="{px1}" y1="{y(im):.1f}" y2="{y(im):.1f}" stroke="{t["ink2"]}" stroke-width="1.5" stroke-dasharray="6 5"/>'
        f'<line x1="{px0}" x2="{px1}" y1="{y(-im):.1f}" y2="{y(-im):.1f}" stroke="{t["ink2"]}" stroke-width="1.5" stroke-dasharray="6 5"/>'
        f'<text x="{px0 + 10}" y="{y(im) - 9:.1f}" class="band">Options imply ±{pct(im)} this time</text>'
    )

    slot = (px1 - px0) / len(history)
    bw, r = 54, 4
    bars = []
    for i, rec in enumerate(history):
        cx = px0 + slot * (i + 0.5)
        mv = rec["move"]
        color = t["up"] if mv >= 0 else t["down"]
        y0, y1 = mid, y(mv)
        x = cx - bw / 2
        if abs(y1 - y0) < r:  # too small for rounded corners
            top = min(y0, y1)
            bars.append(f'<rect x="{x:.1f}" y="{top - 1:.1f}" width="{bw}" height="{max(abs(y1 - y0), 2):.1f}" fill="{color}"/>')
        elif mv >= 0:  # round only the data end (top)
            bars.append(f'<path d="M{x:.1f},{y0:.1f} V{y1 + r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} H{x + bw - r:.1f} '
                        f'Q{x + bw:.1f},{y1:.1f} {x + bw:.1f},{y1 + r:.1f} V{y0:.1f} Z" fill="{color}"/>')
        else:  # round only the data end (bottom)
            bars.append(f'<path d="M{x:.1f},{y0:.1f} V{y1 - r:.1f} Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f} H{x + bw - r:.1f} '
                        f'Q{x + bw:.1f},{y1:.1f} {x + bw:.1f},{y1 - r:.1f} V{y0:.1f} Z" fill="{color}"/>')
        label_y = y1 - 10 if mv >= 0 else y1 + 22
        bars.append(f'<text x="{cx:.1f}" y="{label_y:.1f}" text-anchor="middle" class="val">{mv * 100:+.1f}%</text>')
        d = date.fromisoformat(rec["date"])
        bars.append(f'<text x="{cx:.1f}" y="{py1 + 30}" text-anchor="middle" class="axis">{d:%b} ’{d:%y}</text>')

    lines = textwrap.wrap(b["one_line"], 84)
    brief = "".join(f'<text x="56" y="{186 + i * 36}" class="brief">{escape(s)}</text>' for i, s in enumerate(lines))
    tags_y = 186 + len(lines) * 36 + 8
    tags, tx = [], 56
    for label in (f"Sentiment: {b['sentiment']}", f"Expectations bar: {b['expectations_bar']}"):
        tw = len(label) * 8.6 + 28
        tags.append(f'<rect x="{tx}" y="{tags_y}" width="{tw:.0f}" height="32" rx="16" fill="{t["band"]}"/>'
                    f'<text x="{tx + tw / 2:.0f}" y="{tags_y + 21}" text-anchor="middle" class="pill">{escape(label)}</text>')
        tx += tw + 10

    when = f"Reports {'after the close' if f['time_of_day'] == 'after-hours' else 'before the open'} · {date.fromisoformat(f['report_date']):%b %-d, %Y}"
    legend_x = px1 - 250
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Sample brief for {f['symbol']}: {escape(b['one_line'])}">
<style>
  text {{ font-family: {FONT}; }}
  .sym {{ font-size: 44px; font-weight: 700; letter-spacing: -0.5px; fill: {t["ink"]}; }}
  .name {{ font-size: 22px; fill: {t["ink2"]}; }}
  .when {{ font-size: 16px; fill: {t["muted"]}; }}
  .eyebrow {{ font-size: 13px; font-weight: 600; letter-spacing: 2px; fill: {t["muted"]}; }}
  .brief {{ font-size: 25px; fill: {t["ink"]}; }}
  .pill {{ font-size: 15px; font-weight: 500; fill: {t["ink2"]}; }}
  .ctitle {{ font-size: 17px; font-weight: 600; fill: {t["ink"]}; }}
  .csub {{ font-size: 15px; fill: {t["ink2"]}; }}
  .axis {{ font-size: 13px; fill: {t["muted"]}; font-variant-numeric: tabular-nums; }}
  /* Labels get a surface-colored halo so they stay legible where they cross the dashed band lines. */
  .val, .band {{ stroke: {t["surface"]}; stroke-width: 5px; stroke-linejoin: round; paint-order: stroke; }}
  .val {{ font-size: 13px; font-weight: 600; fill: {t["ink2"]}; font-variant-numeric: tabular-nums; }}
  .band {{ font-size: 14px; font-weight: 600; fill: {t["ink"]}; }}
  .legend {{ font-size: 14px; fill: {t["ink2"]}; }}
</style>
<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="16" fill="{t["surface"]}" stroke="{t["border"]}"/>
<text x="56" y="84" class="sym">{escape(f['symbol'])}</text>
<text x="{56 + len(f['symbol']) * 30 + 18}" y="83" class="name">{escape(f['name'])}</text>
<text x="{w - 56}" y="82" text-anchor="end" class="when">{escape(when)}</text>
<text x="56" y="144" class="eyebrow">AI BRIEF</text>
{brief}
{"".join(tags)}
<text x="56" y="{py0 - 52}" class="ctitle">Stock move after each of the last {len(history)} reports</text>
<text x="56" y="{py0 - 28}" class="csub">Average move {pct(f['avg_abs_earnings_move'])}, largest {pct(f['max_abs_earnings_move'])}. Shaded: the range options are pricing now.</text>
<rect x="{legend_x}" y="{py0 - 64}" width="12" height="12" rx="3" fill="{t["up"]}"/><text x="{legend_x + 20}" y="{py0 - 53}" class="legend">Stock rose</text>
<rect x="{legend_x + 120}" y="{py0 - 64}" width="12" height="12" rx="3" fill="{t["down"]}"/><text x="{legend_x + 140}" y="{py0 - 53}" class="legend">Stock fell</text>
{"".join(ticks)}
{band}
<line x1="{px0}" x2="{px1}" y1="{mid}" y2="{mid}" stroke="{t["axis"]}" stroke-width="1.5"/>
{"".join(bars)}
</svg>
"""


# ---------------------------------------------------------------- email screenshot

FRAME_CSS = """
html, body { margin: 0; background: transparent; }
.win { margin: 24px; border-radius: 14px; overflow: hidden; background: #fff; height: 1352px; position: relative;
       box-shadow: 0 1px 2px rgba(0,0,0,.08), 0 10px 30px rgba(0,0,0,.14); border: 1px solid rgba(11,11,11,.10); }
.bar { height: 40px; background: #f0efec; display: flex; align-items: center; gap: 8px; padding: 0 16px; }
.bar i { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.hdr { padding: 20px 32px 16px; border-bottom: 1px solid #e1e0d9; font-family: -apple-system, system-ui, sans-serif; }
.subj { font-size: 22px; font-weight: 650; color: #0b0b0b; }
.meta { margin-top: 8px; font-size: 13px; color: #52514e; }
.meta b { color: #0b0b0b; font-weight: 600; }
.body { padding: 4px 16px; }
.body body, .body { max-width: none; }
.fade { position: absolute; left: 0; right: 0; bottom: 0; height: 220px;
        background: linear-gradient(rgba(255,255,255,0), #fff 85%); }
"""


def email_png(db: Database, run_date: str, out: Path) -> None:
    # Without a previous date the digest skips "Last session's results", so the overview flows straight into the briefs.
    digest = build(db, run_date, None, digest=True, digest_rows=15)
    import markdown

    body = markdown.markdown(digest, extensions=["tables", "md_in_html"])
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>{EMAIL_CSS}{FRAME_CSS}</style></head><body>
<div class="win">
  <div class="bar"><i style="background:#ec6a5e"></i><i style="background:#f4bf4f"></i><i style="background:#61c554"></i></div>
  <div class="hdr"><div class="subj">{escape(email_subject(db, run_date))}</div>
    <div class="meta"><b>earnings-scanner</b> &nbsp;to&nbsp; you@example.com &nbsp;·&nbsp; {date.fromisoformat(run_date):%a, %b %-d} &nbsp;·&nbsp; 📎 earnings-{run_date}.html</div></div>
  <div class="body">{body}</div>
  <div class="fade"></div>
</div></body></html>"""
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "email.html"
        html_path.write_text(page)
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
             "--default-background-color=00000000", "--window-size=1048,1400", f"--screenshot={out}",
             html_path.as_uri()],
            check=True, capture_output=True,
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help="run date to draw from (YYYY-MM-DD)")
    p.add_argument("--symbol", required=True, help="company for the sample brief card")
    p.add_argument("--no-png", action="store_true", help="skip the Chrome screenshot")
    args = p.parse_args()

    db = Database(load_config().db_path)
    facts, briefs = db.facts(args.date), db.briefs(args.date)
    f, b = facts[args.symbol], briefs[args.symbol]
    largest = sorted((x for x in facts.values() if x.get("implied_move")), key=lambda x: -(x.get("market_cap") or 0))[:14]
    ticker = [f"{x['symbol']}  {TIME_LABEL.get(x['time_of_day'], '?')}  implied ±{pct(x['implied_move'])}" for x in largest]

    OUT.mkdir(parents=True, exist_ok=True)
    for mode, t in THEMES.items():
        (OUT / f"banner-{mode}.svg").write_text(banner(t, ticker))
        (OUT / f"brief-card-{mode}.svg").write_text(brief_card(t, f, b))
    if not args.no_png:
        email_png(db, args.date, OUT / "email.png")
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
