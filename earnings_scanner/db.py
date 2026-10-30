from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    companies INTEGER,
    briefs INTEGER,
    report_path TEXT,
    error TEXT
);

-- One row per company per report date, straight from the Nasdaq earnings calendar.
CREATE TABLE IF NOT EXISTS earnings_calendar (
    report_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    time_of_day TEXT,
    market_cap REAL,
    fiscal_quarter TEXT,
    eps_forecast REAL,
    num_estimates INTEGER,
    last_year_report_date TEXT,
    last_year_eps REAL,
    eps_actual REAL,
    surprise_pct REAL,
    raw_json TEXT,
    first_seen TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (report_date, symbol)
);

-- Raw payload per data source (nasdaq, yahoo, sec) per run date, for later re-analysis.
CREATE TABLE IF NOT EXISTS snapshots (
    run_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    source TEXT NOT NULL,
    data_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (run_date, symbol, source)
);

-- Normalized key metrics derived from the snapshots (what the report and briefs use).
CREATE TABLE IF NOT EXISTS facts (
    run_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (run_date, symbol)
);

CREATE TABLE IF NOT EXISTS news (
    url TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT,
    published_at TEXT,
    feed TEXT,
    first_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS news_symbol ON news (symbol, published_at);

CREATE TABLE IF NOT EXISTS filings (
    accession TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    cik INTEGER,
    form TEXT,
    filed TEXT,
    items TEXT,
    description TEXT,
    url TEXT
);
CREATE INDEX IF NOT EXISTS filings_symbol ON filings (symbol, filed);

-- AI briefs; symbol '__OVERVIEW__' holds the daily cross-company overview.
CREATE TABLE IF NOT EXISTS briefs (
    run_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    model TEXT,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_date, symbol)
);
"""

OVERVIEW = "__OVERVIEW__"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # runs
    def start_run(self, run_date: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (run_date, started_at, status) VALUES (?, ?, 'running')", (run_date, now())
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, status: str, **fields: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        sql = f"UPDATE runs SET status = ?, finished_at = ?{', ' + cols if cols else ''} WHERE id = ?"
        self.conn.execute(sql, (status, now(), *fields.values(), run_id))
        self.conn.commit()

    # calendar
    def upsert_calendar(self, rows: Iterable[dict]) -> None:
        ts = now()
        self.conn.executemany(
            """
            INSERT INTO earnings_calendar (report_date, symbol, name, time_of_day, market_cap, fiscal_quarter,
                eps_forecast, num_estimates, last_year_report_date, last_year_eps, eps_actual, surprise_pct,
                raw_json, first_seen, updated_at)
            VALUES (:report_date, :symbol, :name, :time_of_day, :market_cap, :fiscal_quarter, :eps_forecast,
                :num_estimates, :last_year_report_date, :last_year_eps, :eps_actual, :surprise_pct,
                :raw_json, :ts, :ts)
            ON CONFLICT (report_date, symbol) DO UPDATE SET
                name = excluded.name,
                time_of_day = excluded.time_of_day,
                market_cap = COALESCE(excluded.market_cap, market_cap),
                fiscal_quarter = excluded.fiscal_quarter,
                eps_forecast = COALESCE(excluded.eps_forecast, eps_forecast),
                num_estimates = COALESCE(excluded.num_estimates, num_estimates),
                last_year_report_date = COALESCE(excluded.last_year_report_date, last_year_report_date),
                last_year_eps = COALESCE(excluded.last_year_eps, last_year_eps),
                eps_actual = COALESCE(excluded.eps_actual, eps_actual),
                surprise_pct = COALESCE(excluded.surprise_pct, surprise_pct),
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            """,
            [{**r, "raw_json": json.dumps(r.get("raw")), "ts": ts} for r in rows],
        )
        self.conn.commit()

    def calendar(self, report_date: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM earnings_calendar WHERE report_date = ? ORDER BY market_cap DESC NULLS LAST",
            (report_date,),
        ).fetchall()
        return [dict(r) for r in rows]

    # per-company data
    def save_snapshot(self, run_date: str, symbol: str, source: str, data: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?, ?)",
            (run_date, symbol, source, json.dumps(data), now()),
        )

    def save_facts(self, run_date: str, symbol: str, facts: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO facts VALUES (?, ?, ?)", (run_date, symbol, json.dumps(facts)))

    def facts(self, run_date: str) -> dict[str, dict]:
        rows = self.conn.execute("SELECT symbol, data_json FROM facts WHERE run_date = ?", (run_date,))
        return {r["symbol"]: json.loads(r["data_json"]) for r in rows}

    def save_news(self, symbol: str, items: list[dict]) -> None:
        ts = now()
        self.conn.executemany(
            "INSERT OR IGNORE INTO news VALUES (:url, :symbol, :title, :source, :published_at, :feed, :ts)",
            [{**it, "symbol": symbol, "ts": ts} for it in items],
        )

    def save_filings(self, symbol: str, cik: int | None, filings: list[dict]) -> None:
        self.conn.executemany(
            "INSERT OR IGNORE INTO filings VALUES (:accession, :symbol, :cik, :form, :filed, :items, :description, :url)",
            [{**f, "symbol": symbol, "cik": cik, "items": ",".join(f["items"])} for f in filings],
        )

    def save_brief(self, run_date: str, symbol: str, model: str, brief: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO briefs VALUES (?, ?, ?, ?, ?)",
            (run_date, symbol, model, json.dumps(brief), now()),
        )
        self.conn.commit()

    def briefs(self, run_date: str) -> dict[str, dict]:
        rows = self.conn.execute("SELECT symbol, data_json FROM briefs WHERE run_date = ?", (run_date,))
        return {r["symbol"]: json.loads(r["data_json"]) for r in rows}

    def commit(self) -> None:
        self.conn.commit()
