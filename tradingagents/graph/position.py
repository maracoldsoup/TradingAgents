# TradingAgents/graph/position.py
"""Format the caller's current-position state into prompt context.

Why this exists (pilot #1, 2026-07): the pipeline was position-stateless —
every day a fresh committee decided as if flat, so a "6-12 month horizon"
thesis got flipped to Sell within 1-4 days and 44% of rally walked past a
3% average position. The trader and PM must know what they already hold.

Data honesty rule: only facts the caller provides are stated. No P&L is
computed here beyond arithmetic on the given numbers; nothing is guessed.
"""

from __future__ import annotations

from typing import Any


def format_position_context(position: dict[str, Any] | None) -> str:
    """Render a position dict into an English prompt block.

    Expected keys (all optional): ``shares``, ``entry_price``,
    ``current_price``, ``entry_date``, ``stop``.
    Returns '' when position is None; an explicit flat statement when the
    dict says shares==0 — "unknown" and "flat" are different facts.
    """
    if position is None:
        return ""
    shares = position.get("shares") or 0
    if not shares:
        return (
            "CURRENT POSITION: FLAT (no holding). A Buy opens a new position; "
            "Sell/exit language is not applicable to an existing holding."
        )
    parts = [f"CURRENT POSITION: LONG {shares:g} shares"]
    entry = position.get("entry_price")
    if entry:
        parts.append(f"entered at {entry:g}")
    if position.get("entry_date"):
        parts.append(f"on {position['entry_date']}")
    current = position.get("current_price")
    if entry and current:
        pnl = (current / entry - 1.0) * 100.0
        parts.append(f"unrealized P&L {pnl:+.1f}%")
    if position.get("stop"):
        parts.append(f"armed stop {position['stop']:g}")
    body = ", ".join(parts) + "."
    guidance = (
        " Decide about THIS holding: keep it (Hold), add to it (Buy), or exit "
        "(Sell). Do not re-argue the original entry from scratch; weigh the "
        "thesis against what has changed since entry, and keep your stated "
        "time horizon consistent with your action."
    )
    return body + guidance
