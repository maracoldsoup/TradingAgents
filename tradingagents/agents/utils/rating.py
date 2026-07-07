"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

The same five-tier scale (Buy, Overweight, Hold, Underweight, Sell) is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.
"""

from __future__ import annotations

import re

# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

RATING_TO_ACTION: dict[str, str] = {
    "Buy": "Buy",
    "Overweight": "Buy",
    "Hold": "Hold",
    "Underweight": "Sell",
    "Sell": "Sell",
}

RATING_TO_BIAS: dict[str, str] = {
    "Buy": "bullish",
    "Overweight": "bullish",
    "Hold": "neutral",
    "Underweight": "bearish",
    "Sell": "bearish",
}

RATING_TO_SCORE: dict[str, int] = {
    "Buy": 2,
    "Overweight": 1,
    "Hold": 0,
    "Underweight": -1,
    "Sell": -2,
}

_RATING_BY_LOWER = {r.lower(): r for r in RATINGS_5_TIER}
_RATING_SET = set(_RATING_BY_LOWER)

# Matches "Rating: X" / "rating - X" / "Rating: **X**" — tolerates markdown
# bold wrappers and either a colon or hyphen separator.
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)


def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from prose text.

    Two-pass strategy:
    1. Look for an explicit "Rating: X" label (tolerant of markdown bold).
    2. Fall back to the first 5-tier rating word found anywhere in the text.

    Returns a Title-cased rating string, or ``default`` if no rating word appears.
    """
    for line in text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m and m.group(1).lower() in _RATING_SET:
            return _RATING_BY_LOWER[m.group(1).lower()]

    for line in text.splitlines():
        for word in line.lower().split():
            clean = word.strip("*:.,")
            if clean in _RATING_SET:
                return _RATING_BY_LOWER[clean]

    return default


def rating_to_action(rating: str) -> str:
    return RATING_TO_ACTION.get(rating, "Hold")


def rating_to_bias(rating: str) -> str:
    return RATING_TO_BIAS.get(rating, "neutral")


def rating_to_score(rating: str) -> int:
    return RATING_TO_SCORE.get(rating, 0)
