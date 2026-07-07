# TradingAgents/dashboard/events.py
"""Translate LangGraph state chunks into dashboard SSE events.

Pure, stateful-diff translator: feed it the ``stream_mode="values"`` chunks
in order and it emits only *new* information as JSON-serializable event
dicts. Keeping this free of FastAPI/asyncio makes it unit-testable without
a server or an LLM.
"""

from __future__ import annotations

import re
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

_MAX_SUMMARY_CHARS = 360
_MAX_BULLETS = 4
_BOILERPLATE_PATTERNS = (
    "final transaction proposal",
    "transaction proposal",
    "fundamental analysis",
    "technical analysis",
    "comprehensive report",
    "target stock",
    "analysis date",
    "분석 보고서",
    "종합 보고서",
    "보고서",
    "대상 종목",
    "분석 기준",
)

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
                    {
                        "type": "report",
                        "agent": agent,
                        "content": content,
                        **summarize_content(content),
                    }
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
                {"type": "debate", "speaker": "judge", "content": judge, **summarize_content(judge)}
            )

        # ── Stage 3: trader ──
        trader = (chunk.get("trader_investment_plan") or "").strip()
        if trader and not self._trader_sent:
            self._trader_sent = True
            events.append({"type": "trader", "content": trader, **summarize_content(trader)})

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
                    **summarize_content(final),
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
        return [{"type": kind, "speaker": speaker, "content": delta, **summarize_content(delta)}]


def clean_markdown(text: str) -> str:
    """Convert agent markdown into compact dashboard prose."""
    value = str(text or "")
    value = re.sub(r"```[\s\S]*?```", " ", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = re.sub(r"^#{1,6}\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*[-*]\s+", "- ", value, flags=re.MULTILINE)
    value = value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def compact_text(text: str, max_chars: int = _MAX_SUMMARY_CHARS) -> str:
    """Collapse whitespace and clamp text without splitting too harshly."""
    value = re.sub(r"\s+", " ", clean_markdown(text)).strip()
    if len(value) <= max_chars:
        return value
    clipped = value[: max_chars - 1].rstrip()
    boundary = max(clipped.rfind("."), clipped.rfind("다."), clipped.rfind(";"))
    if boundary >= max_chars // 2:
        clipped = clipped[: boundary + 1]
    return clipped.rstrip() + "..."


def _strip_claim_prefix(text: str) -> str:
    value = text.strip(" -\t")
    value = re.sub(r"^\[[^\]]+\]\s*", "", value)
    value = re.sub(
        r"^(final transaction proposal|overall sentiment|reasoning|rationale|"
        r"investment thesis|recommendation|rating|action|bull analyst|bear analyst|"
        r"research manager|trader|aggressive|neutral|conservative)\s*[:：-]\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"^[가-힣A-Za-z\s·]+(?:매니저|분석가|위원|트레이더)\s*[:：-]\s*", "", value)
    return value.strip()


def _is_boilerplate_line(text: str) -> bool:
    value = text.strip().lower()
    if len(value) < 8:
        return True
    return any(pattern in value for pattern in _BOILERPLATE_PATTERNS)


def extract_bullets(text: str, limit: int = _MAX_BULLETS) -> list[str]:
    """Pick readable bullet-like claims from markdown/prose."""
    clean = clean_markdown(text)
    bullets: list[str] = []
    for line in clean.splitlines():
        stripped = _strip_claim_prefix(line)
        if not stripped or _is_boilerplate_line(stripped):
            continue
        looks_like_bullet = line.lstrip().startswith(("-", "*")) or re.match(
            r"^\d+[.)]\s+", stripped
        )
        if looks_like_bullet or len(stripped) >= 20:
            stripped = re.sub(r"^\d+[.)]\s+", "", stripped)
            bullets.append(compact_text(stripped, 140))
        if len(bullets) >= limit:
            break
    if bullets:
        return bullets

    sentences = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s+", compact_text(clean, 700))
    claims = []
    for sentence in sentences:
        claim = _strip_claim_prefix(sentence)
        if len(claim) > 16 and not _is_boilerplate_line(claim):
            claims.append(compact_text(claim, 140))
        if len(claims) >= limit:
            break
    return claims


def summarize_content(text: str) -> dict[str, Any]:
    """Return UI-friendly fields while preserving the raw content."""
    bullets = extract_bullets(text)
    summary = compact_text(" ".join(bullets[:2]) if bullets else text)
    headline = bullets[0] if bullets else summary
    return {
        "summary": summary,
        "headline": compact_text(headline, 120),
        "bullets": bullets,
    }
