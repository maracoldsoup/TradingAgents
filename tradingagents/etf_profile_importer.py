"""Import local ETF holding files into structured no-LLM profile JSON."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from tradingagents.content_profiles import normalize_etf_profile

_COLUMN_ALIASES = {
    "ticker": ("ticker", "symbol", "holding ticker", "security ticker", "종목코드", "티커"),
    "name": ("name", "holding name", "security name", "company", "종목명", "이름"),
    "weight_pct": ("weight_pct", "weight", "weight (%)", "% weight", "비중", "비중(%)"),
    "sector": ("sector", "gics sector", "industry", "섹터", "업종"),
    "country": ("country", "country/region", "location", "market", "국가", "지역"),
}


def _norm_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first(row: dict[str, Any], field: str) -> str:
    normalized = {_norm_key(key): value for key, value in row.items()}
    for alias in _COLUMN_ALIASES[field]:
        value = normalized.get(_norm_key(alias))
        if value not in (None, ""):
            return _clean_text(value)
    return ""


def _float_or_none(value: Any, *, weight_scale: str = "percent") -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    had_percent = "%" in text
    text = text.replace("%", "")
    try:
        number = float(text)
    except ValueError:
        return None
    if weight_scale == "fraction" or (weight_scale == "auto" and not had_percent and abs(number) <= 1):
        number *= 100
    return round(number, 4)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_holding_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        return _read_csv(path)
    payload = _read_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        if payload.get("profile_type") == "etf":
            return list(payload.get("holdings") or [])
        rows = payload.get("holdings") or payload.get("rows") or payload.get("data")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def normalize_holding_rows(rows: list[dict[str, Any]], *, weight_scale: str = "percent") -> list[dict[str, Any]]:
    holdings: list[dict[str, Any]] = []
    for row in rows:
        ticker = _first(row, "ticker")
        name = _first(row, "name") or ticker
        if not (ticker or name):
            continue
        holding: dict[str, Any] = {}
        if ticker:
            holding["ticker"] = ticker
        if name:
            holding["name"] = name
        weight = _float_or_none(_first(row, "weight_pct"), weight_scale=weight_scale)
        if weight is not None:
            holding["weight_pct"] = weight
        sector = _first(row, "sector")
        if sector:
            holding["sector"] = sector
        country = _first(row, "country")
        if country:
            holding["country"] = country
        holdings.append(holding)
    return sorted(holdings, key=lambda item: item.get("weight_pct", -1), reverse=True)


def _aggregate(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        name = _clean_text(row.get(field))
        weight = row.get("weight_pct")
        if not name or weight in (None, ""):
            continue
        try:
            totals[name] += float(weight)
        except (TypeError, ValueError):
            continue
    return [
        {"name": name, "weight_pct": round(weight, 4)}
        for name, weight in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def import_etf_profile(
    *,
    holdings_path: Path,
    ticker: str,
    name: str | None = None,
    issuer: str | None = None,
    benchmark: str | None = None,
    expense_ratio_pct: float | None = None,
    aum: str | None = None,
    currency: str | None = None,
    as_of: str | None = None,
    source: str | None = None,
    weight_scale: str = "percent",
    top_n: int | None = None,
) -> dict[str, Any]:
    """Build a normalized ETF profile from a local holdings file."""
    rows = load_holding_rows(holdings_path)
    holdings = normalize_holding_rows(rows, weight_scale=weight_scale)
    if top_n is not None:
        holdings = holdings[: max(int(top_n), 0)]
    profile = {
        "profile_type": "etf",
        "ticker": ticker,
        "name": name or ticker,
        "issuer": issuer,
        "benchmark": benchmark,
        "expense_ratio_pct": expense_ratio_pct,
        "aum": aum,
        "currency": currency,
        "as_of": as_of,
        "source": source or f"local_file:{holdings_path.name}",
        "holdings": holdings,
        "sectors": _aggregate(holdings, "sector"),
        "countries": _aggregate(holdings, "country"),
    }
    return normalize_etf_profile(profile)

