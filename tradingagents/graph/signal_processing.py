"""Extract the 5-tier portfolio rating from the Portfolio Manager's decision.

The Portfolio Manager produces a typed ``PortfolioDecision`` via structured
output and renders it to markdown that always carries a ``**Rating**: X``
header (see :func:`tradingagents.agents.schemas.render_pm_decision`).  The
deterministic heuristic in :mod:`tradingagents.agents.utils.rating` is more
than sufficient to extract that rating; no extra LLM call is needed.

This module exists for backwards compatibility with callers that expect a
``SignalProcessor.process_signal(text)`` interface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from tradingagents.agents.utils.rating import (
    parse_rating,
    rating_to_action,
    rating_to_bias,
    rating_to_score,
)


@dataclass(frozen=True)
class TradeSignal:
    """Machine-readable final trade signal for logs and dashboards."""

    schema_version: int
    rating: str
    action: str
    bias: str
    score: int
    source: str = "portfolio_manager"

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


def compose_levels(
    trader_structured: dict | None,
    pm_structured: dict | None,
) -> dict[str, float]:
    """Merge trader and PM structured fields into canonical price levels.

    The PM speaks last, so its values override the trader's; the trader's
    entry survives when the PM omits one (the PM often only restates stop
    and target). Only fields the models actually emitted appear — the
    dashboard's regex extractor remains a fallback for free-text runs.
    """
    trader = trader_structured or {}
    pm = pm_structured or {}
    mapping = (
        ("entry", ("entry_price",)),
        ("stop", ("stop_loss",)),
        ("target", ("price_target",)),
        ("position_size_pct", ("position_size_pct",)),
    )
    levels: dict[str, float] = {}
    for canonical, field_names in mapping:
        for source in (pm, trader):  # PM 우선
            for field in field_names:
                value = source.get(field)
                if isinstance(value, (int, float)) and value > 0:
                    levels[canonical] = float(value)
                    break
            if canonical in levels:
                break
    return levels


def normalize_trade_signal(
    full_signal: str,
    trader_structured: dict | None = None,
    pm_structured: dict | None = None,
) -> dict:
    """Convert Portfolio Manager prose into the canonical signal vocabulary."""
    rating = parse_rating(full_signal)
    signal = TradeSignal(
        schema_version=1,
        rating=rating,
        action=rating_to_action(rating),
        bias=rating_to_bias(rating),
        score=rating_to_score(rating),
    ).as_dict()
    levels = compose_levels(trader_structured, pm_structured)
    if levels:
        signal["levels"] = levels
    return signal


class SignalProcessor:
    """Read the 5-tier rating out of a Portfolio Manager decision."""

    def __init__(self, quick_thinking_llm: Any = None):
        # The LLM argument is accepted for backwards compatibility but no
        # longer used: the PM's structured output guarantees the rating is
        # parseable from the rendered markdown without a second LLM call.
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str) -> str:
        """Return one of Buy / Overweight / Hold / Underweight / Sell."""
        return parse_rating(full_signal)
