from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from .config import load_config
from .db import Database
from .pipeline import email_report, run
from .report import render
from .util import previous_weekday


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="earnings_scanner", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Fetch the calendar, research today's reporters, write the report")
    p_run.add_argument("--date", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD (default: today)")
    p_run.add_argument("--symbols", help="Comma-separated symbols to research (ignores market-cap filter)")
    p_run.add_argument("--limit", type=int, help="Research at most N companies (largest first)")
    p_run.add_argument("--no-brief", action="store_true", help="Skip Claude briefs")
    p_run.add_argument("--no-email", action="store_true", help="Don't email the report")
    p_run.add_argument("-v", "--verbose", action="store_true")

    p_rep = sub.add_parser("report", help="Re-render the Markdown report from the database")
    p_rep.add_argument("--date", type=date.fromisoformat, default=date.today())

    p_mail = sub.add_parser("email", help="Email a report already in the database (e.g. to test the email settings)")
    p_mail.add_argument("--date", type=date.fromisoformat, default=date.today())

    args = parser.parse_args(argv)
    cfg = load_config()

    level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(cfg.logs_dir / f"run-{date.today().isoformat()}.log"),
    ]
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    for noisy in ("urllib3", "yfinance", "peewee", "httpx", "httpx2", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.cmd == "run":
        symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
        path = run(cfg, args.date, brief=not args.no_brief, email=not args.no_email, symbols=symbols, limit=args.limit)
        print(path)
    elif args.cmd == "report":
        db = Database(cfg.db_path)
        print(render(db, args.date.isoformat(), previous_weekday(args.date).isoformat(), cfg.reports_dir))
        db.close()
    elif args.cmd == "email":
        db = Database(cfg.db_path)
        ok = email_report(cfg, db, args.date.isoformat(), previous_weekday(args.date).isoformat())
        db.close()
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
