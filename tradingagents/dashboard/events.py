# TradingAgents/dashboard/events.py
"""Translate LangGraph state chunks into dashboard SSE events.

Pure, stateful-diff translator: feed it the ``stream_mode="values"`` chunks
in order and it emits only *new* information as JSON-serializable event
dicts. Keeping this free of FastAPI/asyncio makes it unit-testable without
a server or an LLM.
"""

from __future__ import annotations

from typing import Any

from tradingagents.agents.utils.rating import (
    parse_rating,
    rating_to_action,
    rating_to_bias,
    rating_to_score,
)

# report_key → (agent key used by the frontend, stage label)
REPORT_AGENTS = {
    "market_report": "market",
    "sentiment_report": "sentiment",
    "news_report": "news",
    "fundamentals_report": "fundamentals",
}

_DEBATE_SPEAKERS = (
    ("bull_history", "bull"),
    ("bear_history", "bear"),
)
_RISK_SPEAKERS = (
    ("aggressive_history", "aggressive"),
    ("conservative_history", "conservative"),
    ("neutral_history", "neutral"),
)


class DashboardEventTranslator:
    """Diffs successive state chunks into incremental dashboard events."""

    def __init__(self) -> None:
        self._seen_reports: dict[str, str] = {}
        self._debate_len: dict[str, int] = {}
        self._risk_len: dict[str, int] = {}
        self._debate_judge_sent = False
        self._trader_sent = False
        self._final_sent = False
        self._telemetry_sent = False

    def translate(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        # ── Stage 1: analyst reports ──
        for report_key, agent in REPORT_AGENTS.items():
            content = (chunk.get(report_key) or "").strip()
            if content and self._seen_reports.get(report_key) != content:
                self._seen_reports[report_key] = content
                events.append(
                    {"type": "report", "agent": agent, "content": content}
                )

        telemetry = chunk.get("analyst_telemetry") or {}
        if telemetry and not self._telemetry_sent:
            self._telemetry_sent = True
            events.append({"type": "telemetry", "analysts": telemetry})

        # ── Stage 2: research debate ──
        debate = chunk.get("investment_debate_state") or {}
        for field, speaker in _DEBATE_SPEAKERS:
            events.extend(
                self._history_delta(debate, field, speaker, self._debate_len)
            )
        judge = (debate.get("judge_decision") or "").strip()
        if judge and not self._debate_judge_sent:
            self._debate_judge_sent = True
            events.append(
                {"type": "debate", "speaker": "judge", "content": judge}
            )

        # ── Stage 3: trader ──
        trader = (chunk.get("trader_investment_plan") or "").strip()
        if trader and not self._trader_sent:
            self._trader_sent = True
            events.append({"type": "trader", "content": trader})

        # ── Stage 4: risk committee ──
        risk = chunk.get("risk_debate_state") or {}
        for field, speaker in _RISK_SPEAKERS:
            events.extend(
                self._history_delta(risk, field, speaker, self._risk_len, kind="risk")
            )

        # ── Stage 5: final decision ──
        final = (chunk.get("final_trade_decision") or "").strip()
        if final and not self._final_sent:
            self._final_sent = True
            rating = parse_rating(final)
            events.append(
                {
                    "type": "final",
                    "content": final,
                    "rating": rating,
                    "action": rating_to_action(rating),
                    "bias": rating_to_bias(rating),
                    "score": rating_to_score(rating),
                }
            )

        return events

    @staticmethod
    def _delta_text(history: str, prev_len: int) -> str:
        return history[prev_len:].strip()

    def _history_delta(
        self,
        state: dict[str, Any],
        field: str,
        speaker: str,
        ledger: dict[str, int],
        kind: str = "debate",
    ) -> list[dict[str, Any]]:
        history = state.get(field) or ""
        prev = ledger.get(field, 0)
        if len(history) <= prev:
            return []
        delta = self._delta_text(history, prev)
        ledger[field] = len(history)
        if not delta:
            return []
        return [{"type": kind, "speaker": speaker, "content": delta}]
