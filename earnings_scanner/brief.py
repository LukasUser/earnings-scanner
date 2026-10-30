"""Claude-written pre-earnings briefs (per company) and a daily cross-company overview."""

from __future__ import annotations

import json
import logging
import threading

import anthropic

log = logging.getLogger(__name__)

# Models that accept server-side refusal fallbacks (fallbacks: "default").
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

_str_list = {"type": "array", "items": {"type": "string"}}

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "one_line": {"type": "string", "description": "One plain sentence, at most 30 words: the setup going into this report."},
        "sentiment": {"type": "string", "enum": ["bullish", "neutral", "bearish", "mixed"]},
        "expectations_bar": {"type": "string", "enum": ["low", "moderate", "high"]},
    },
    "required": ["one_line", "sentiment", "expectations_bar"],
    "additionalProperties": False,
}

OVERVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "At most 2 sentences on the day's earnings slate."},
        "top_setups": {
            "type": "array",
            "description": "Up to 5 setups that stand out.",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "reason": {"type": "string", "description": "One short phrase, at most 15 words."},
                },
                "required": ["symbol", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "top_setups"],
    "additionalProperties": False,
}

BRIEF_SYSTEM = """You are an equity research analyst writing a pre-earnings brief for a trader.
You receive structured data collected this morning from Nasdaq, Yahoo Finance, SEC EDGAR and news feeds.

Write exactly one plain sentence of at most 30 words: the single most important thing about this setup, with the one or two numbers that matter most (e.g. implied vs. historical move, estimate revisions, short interest, a notable filing or headline). Ground it in the provided data; headlines are titles only, so don't claim details beyond what a title states.

Do not give buy/sell/hold recommendations or price predictions. Skip anything generic that would apply to any company."""

OVERVIEW_SYSTEM = """You are an equity research analyst summarizing today's earnings slate for a trader, using per-company metrics and briefs prepared this morning.

Keep it short. Summarize the slate in at most two plain sentences. Then pick up to five setups that stand out (large implied moves, big gaps between implied and historical moves, crowded positioning, sharp estimate revisions, notable news or filings), each with a reason of at most 15 words that cites the key number. Do not give buy/sell recommendations."""


class BriefError(Exception):
    pass


class Briefer:
    def __init__(self, model: str, effort: str):
        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self._lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0

    def _call(self, system: str, user: str, schema: dict) -> dict:
        kwargs = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if self.model in FALLBACK_MODELS:
            resp = self.client.beta.messages.create(
                **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
            )
        else:
            resp = self.client.messages.create(**kwargs)

        with self._lock:
            self.input_tokens += resp.usage.input_tokens
            self.output_tokens += resp.usage.output_tokens

        if resp.stop_reason == "refusal":
            category = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise BriefError(f"model declined (category: {category})")
        if resp.stop_reason == "max_tokens":
            raise BriefError("response hit max_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise BriefError(f"no text in response (stop_reason={resp.stop_reason})")
        return json.loads(text)

    def company_brief(self, facts: dict) -> dict:
        user = (
            f"Write the pre-earnings brief for {facts['symbol']} ({facts['name']}), reporting "
            f"{facts['report_date']} ({facts['time_of_day']}).\n\n<data>\n{json.dumps(facts, indent=1)}\n</data>"
        )
        return self._call(BRIEF_SYSTEM, user, BRIEF_SCHEMA)

    def overview(self, run_date: str, rows: list[dict]) -> dict:
        user = (
            f"Today's earnings slate ({run_date}), largest companies first.\n\n"
            f"<companies>\n{json.dumps(rows, indent=1)}\n</companies>"
        )
        return self._call(OVERVIEW_SYSTEM, user, OVERVIEW_SCHEMA)
