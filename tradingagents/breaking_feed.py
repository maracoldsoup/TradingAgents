"""Build a no-LLM breaking-item feed from a Toss rankings snapshot.

Mirrors `content_snapshot.py`'s discipline: deterministic, no LLM call, no
invented numbers. `notable_mover` is never a computed threshold — it is
"was this symbol in Toss's own TOP_GAINERS/TOP_LOSERS ranking", quoted
as-is from `toss_rankings_snapshot`.

Each Korean sentence is templated from fields Toss already returned
(`price.changeRate`, `tradingVolume`, `tradingAmount`, `rank`). If a field
is missing, the sentence drops that clause rather than guessing a value.

Symbols are kept in Toss's own form (e.g. `005930`, not `005930.KS`) with
a separate `market` field. Toss's ranking response does not distinguish
KOSPI from KOSDAQ, so guessing a `.KS`/`.KQ` suffix would fabricate an
identifier the source data doesn't support.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


# Priority order when a symbol appears in multiple rankings: the most
# attention-grabbing membership drives the headline.
_TYPE_PRIORITY = (
    "TOP_GAINERS",
    "TOP_LOSERS",
    "TOSS_SECURITIES_TRADING_AMOUNT",
    "TOSS_SECURITIES_TRADING_VOLUME",
    "MARKET_TRADING_AMOUNT",
    "MARKET_TRADING_VOLUME",
)
_MOVER_TYPES = {"TOP_GAINERS", "TOP_LOSERS"}
_TYPE_LABEL_KO = {
    "TOP_GAINERS": "급등",
    "TOP_LOSERS": "급락",
    "MARKET_TRADING_AMOUNT": "거래대금 상위",
    "MARKET_TRADING_VOLUME": "거래량 상위",
    "TOSS_SECURITIES_TRADING_AMOUNT": "토스증권 거래대금 상위",
    "TOSS_SECURITIES_TRADING_VOLUME": "토스증권 거래량 상위",
}
_CURRENCY_LABEL = {"KRW": "원", "USD": "달러"}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: float | None) -> str | None:
    if value is None:
        return None
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.2f}%"


def _fmt_amount(value: float | None, currency: str | None) -> str | None:
    if value is None:
        return None
    label = _CURRENCY_LABEL.get(str(currency or "").upper(), currency or "")
    return f"{value:,.0f}{label}".strip()


def _group_by_symbol(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip()
        market = str(row.get("market_country") or "").strip()
        if not symbol or not market:
            continue
        grouped.setdefault((market, symbol), []).append(row)
    return grouped


def _primary_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def rank_key(row: dict[str, Any]) -> tuple[int, int]:
        ranking_type = row.get("ranking_type")
        type_index = (
            _TYPE_PRIORITY.index(ranking_type)
            if ranking_type in _TYPE_PRIORITY
            else len(_TYPE_PRIORITY)
        )
        rank = row.get("rank")
        rank_value = int(rank) if isinstance(rank, int) or (isinstance(rank, str) and rank.isdigit()) else 999
        return (type_index, rank_value)

    return min(rows, key=rank_key)


def _headline_ko(symbol: str, primary: dict[str, Any]) -> str:
    ranking_type = str(primary.get("ranking_type") or "")
    label = _TYPE_LABEL_KO.get(ranking_type, ranking_type or "랭킹 등장")
    rank = primary.get("rank")
    rank_part = f" {rank}위" if rank else ""
    return f"{symbol} {label}{rank_part}"


def _summary_ko(primary: dict[str, Any]) -> str:
    price = primary.get("price") if isinstance(primary.get("price"), dict) else {}
    currency = primary.get("currency")
    change_rate = _fmt_pct(_number(price.get("changeRate")))
    trading_amount = _fmt_amount(_number(primary.get("trading_amount")), currency)

    parts: list[str] = []
    if change_rate:
        parts.append(f"등락률 {change_rate}")
    if trading_amount:
        parts.append(f"거래대금 {trading_amount}")
    if not parts:
        return "Toss 랭킹에 등장했습니다."
    return " · ".join(parts)


def _breaking_id(market: str, symbol: str, generated_at: datetime) -> str:
    return f"breaking:{market}:{symbol}:{generated_at.date().isoformat()}"


def build_breaking_items(
    rankings_snapshot: dict[str, Any],
    *,
    generated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build `service_breaking_list` items from a `toss_rankings_snapshot`.

    One item per (market, symbol), even if the symbol appeared in several
    rankings — the headline uses the most notable membership and
    `rankings` lists every membership so nothing is dropped silently.
    """
    from tradingagents.dataflows.toss_rankings import notable_symbols

    if rankings_snapshot.get("artifact") != "toss_rankings_snapshot":
        raise ValueError("build_breaking_items requires a toss_rankings_snapshot artifact")

    generated_at = generated_at or datetime.now()
    rows = notable_symbols(rankings_snapshot)
    grouped = _group_by_symbol(rows)

    items: list[dict[str, Any]] = []
    for (market, symbol), symbol_rows in grouped.items():
        primary = _primary_row(symbol_rows)
        ranking_types = sorted({str(row.get("ranking_type")) for row in symbol_rows})
        items.append({
            "id": _breaking_id(market, symbol, generated_at),
            "ticker": symbol,
            "market": market,
            "kind": "stock",
            "headline_ko": _headline_ko(symbol, primary),
            "summary_ko": _summary_ko(primary),
            "source": "토스증권 랭킹",
            "source_url": None,
            "published_at": rankings_snapshot.get("ranked_at", {}).get(market, {}).get(primary.get("ranking_type"))
            or generated_at.isoformat(timespec="seconds"),
            "notable_mover": bool(_MOVER_TYPES & set(ranking_types)),
            "rankings": ranking_types,
        })

    items.sort(key=lambda item: (not item["notable_mover"], item["market"], item["ticker"]))
    return items


def build_breaking_list_payload(
    rankings_snapshot: dict[str, Any],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Wrap `build_breaking_items` in the `service_breaking_list` envelope."""
    generated_at = generated_at or datetime.now()
    items = build_breaking_items(rankings_snapshot, generated_at=generated_at)
    return {
        "schema_version": 1,
        "artifact": "service_breaking_list",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "count": len(items),
        "items": items,
    }
