"""Structured stock/ETF/theme profile helpers for no-LLM content pilots."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from tradingagents.content_pilot import read_json


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("ticker") or value.get("symbol") or "").strip()
    return str(value or "").strip()


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_weight_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        iterable = [
            {"name": key, "weight_pct": raw_weight}
            for key, raw_weight in value.items()
        ]
    else:
        iterable = _as_list(value)

    for item in iterable:
        if isinstance(item, dict):
            name = _name(item)
            weight = _float_or_none(
                item.get("weight_pct")
                if "weight_pct" in item
                else item.get("weight")
            )
            row = {
                key: item[key]
                for key in ("ticker", "symbol", "name", "sector", "country")
                if item.get(key) not in (None, "")
            }
            if name and "name" not in row:
                row["name"] = name
        else:
            name = _name(item)
            weight = None
            row = {"name": name} if name else {}

        if not row:
            continue
        if weight is not None:
            row["weight_pct"] = round(weight, 4)
        rows.append(row)

    return sorted(rows, key=lambda row: row.get("weight_pct", -1), reverse=True)


def normalize_name_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            name = _name(item)
            row = {
                key: item[key]
                for key in ("ticker", "symbol", "name", "role", "market", "country", "stage")
                if item.get(key) not in (None, "")
            }
            if name and "name" not in row:
                row["name"] = name
        else:
            name = _name(item)
            row = {"name": name} if name else {}
        if row:
            rows.append(row)
    return rows


def normalize_value_chain(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or item.get("name") or "").strip()
        if not stage:
            continue
        row = {
            "stage": stage,
            "description": str(item.get("description") or "").strip(),
            "domestic_names": normalize_name_rows(item.get("domestic_names")),
            "global_names": normalize_name_rows(item.get("global_names")),
            "metrics": normalize_name_rows(item.get("metrics")),
        }
        rows.append({key: val for key, val in row.items() if val not in ("", [])})
    return rows


def normalize_etf_profile(raw: dict[str, Any]) -> dict[str, Any]:
    profile = {
        "schema_version": 1,
        "profile_type": "etf",
        "name": raw.get("name") or raw.get("ticker"),
        "ticker": raw.get("ticker"),
        "issuer": raw.get("issuer"),
        "benchmark": raw.get("benchmark"),
        "expense_ratio_pct": _float_or_none(raw.get("expense_ratio_pct")),
        "aum": raw.get("aum"),
        "currency": raw.get("currency"),
        "as_of": raw.get("as_of"),
        "source": raw.get("source"),
        "holdings": normalize_weight_rows(raw.get("holdings")),
        "sectors": normalize_weight_rows(raw.get("sectors")),
        "countries": normalize_weight_rows(raw.get("countries")),
    }
    return {key: value for key, value in profile.items() if value not in (None, "", [])}


def normalize_theme_profile(raw: dict[str, Any]) -> dict[str, Any]:
    profile = {
        "schema_version": 1,
        "profile_type": "theme",
        "name": raw.get("name") or raw.get("ticker"),
        "ticker": raw.get("ticker"),
        "description": raw.get("description"),
        "as_of": raw.get("as_of"),
        "source": raw.get("source"),
        "value_chain": normalize_value_chain(raw.get("value_chain")),
        "domestic_names": normalize_name_rows(raw.get("domestic_names")),
        "global_names": normalize_name_rows(raw.get("global_names")),
        "catalysts": normalize_name_rows(raw.get("catalysts")),
        "risks": normalize_name_rows(raw.get("risks")),
    }
    return {key: value for key, value in profile.items() if value not in (None, "", [])}


def normalize_stock_profile(raw: dict[str, Any]) -> dict[str, Any]:
    profile = {
        "schema_version": 1,
        "profile_type": "stock",
        "name": raw.get("name") or raw.get("ticker"),
        "ticker": raw.get("ticker"),
        "exchange": raw.get("exchange"),
        "country": raw.get("country"),
        "currency": raw.get("currency"),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "description": raw.get("description"),
        "as_of": raw.get("as_of"),
        "source": raw.get("source"),
        "business_lines": normalize_weight_rows(raw.get("business_lines")),
        "regions": normalize_weight_rows(raw.get("regions")),
        "products": normalize_name_rows(raw.get("products")),
        "peers": normalize_name_rows(raw.get("peers")),
        "catalysts": normalize_name_rows(raw.get("catalysts")),
        "risks": normalize_name_rows(raw.get("risks")),
    }
    return {key: value for key, value in profile.items() if value not in (None, "", [])}


def normalize_profile(raw: dict[str, Any]) -> dict[str, Any]:
    profile_type = str(raw.get("profile_type") or raw.get("asset_type") or raw.get("content_type") or "").lower()
    if profile_type == "stock":
        return normalize_stock_profile(raw)
    if profile_type == "etf":
        return normalize_etf_profile(raw)
    if profile_type == "theme":
        return normalize_theme_profile(raw)
    raise ValueError(f"Unsupported profile type: {profile_type or 'missing'}")


def final_state_from_profile(profile: dict[str, Any]) -> tuple[dict[str, Any], str, datetime | None]:
    content_type = str(profile.get("profile_type") or "").lower()
    ticker = str(profile.get("ticker") or profile.get("name") or "").strip()
    if not ticker:
        raise ValueError("Profile requires ticker or name")

    name = str(profile.get("name") or ticker)
    description = str(profile.get("description") or "")
    as_of = profile.get("as_of")
    source = profile.get("source")
    context = f"{ticker} is a structured {content_type} content profile."
    if name:
        context += f" Name: {name}."
    if source:
        context += f" Source: {source}."
    if content_type == "stock":
        business = " / ".join(
            str(profile.get(key))
            for key in ("sector", "industry")
            if profile.get(key)
        )
        context = f"Company: {name};"
        if business:
            context += f" Business classification: {business};"
        if profile.get("exchange"):
            context += f" Exchange: {profile['exchange']};"
        if profile.get("country"):
            context += f" Country: {profile['country']};"
        if source:
            context += f" Source: {source};"

    fundamentals_parts: list[str] = []
    if content_type == "stock":
        if profile.get("business_lines"):
            labels = []
            for row in profile["business_lines"]:
                weight = row.get("weight_pct")
                suffix = f" {weight:g}%" if weight not in (None, "") else ""
                labels.append(f"{row.get('name') or row.get('ticker')}{suffix}")
            fundamentals_parts.append("사업 구성: " + ", ".join(labels))
        if profile.get("regions"):
            labels = []
            for row in profile["regions"]:
                weight = row.get("weight_pct")
                suffix = f" {weight:g}%" if weight not in (None, "") else ""
                labels.append(f"{row.get('name') or row.get('country')}{suffix}")
            fundamentals_parts.append("지역 노출: " + ", ".join(labels))
        if profile.get("products"):
            fundamentals_parts.append("핵심 제품/서비스: " + ", ".join(_name(row) for row in profile["products"]))
        if profile.get("peers"):
            fundamentals_parts.append("비교 대상: " + ", ".join(_name(row) for row in profile["peers"]))

    catalysts = profile.get("catalysts") or []
    risks = profile.get("risks") or []

    state: dict[str, Any] = {
        "asset_type": content_type,
        "content_type": content_type,
        "instrument_context": context,
        "trade_date": as_of,
        "market_report": description or f"{name} 구성 데이터 기반 콘텐츠 파일럿입니다.",
        "news_report": "",
        "sentiment_report": "",
        "fundamentals_report": "\n".join(fundamentals_parts),
        "investment_debate_state": {
            "bull_history": "\n".join(_name(row) for row in catalysts),
            "bear_history": "\n".join(_name(row) for row in risks),
        },
        "risk_debate_state": {
            "judge_decision": (
                "구성 데이터 기반 설명 콘텐츠입니다. 투자 조언이 아니며, "
                "가격 레벨은 별도 신호가 있을 때만 표시합니다."
            )
        },
        "final_trade_decision": "구성 데이터 기반 설명 콘텐츠입니다. 투자 조언이 아닙니다.",
    }
    if content_type == "stock":
        state["stock_profile"] = profile
    elif content_type == "etf":
        state["etf_profile"] = profile
    elif content_type == "theme":
        state["theme_profile"] = profile
    return state, ticker, None


def _raw_profiles(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        raw_profiles = payload.get("profiles")
        if raw_profiles is None and (
            payload.get("profile_type") or payload.get("asset_type") or payload.get("content_type")
        ):
            raw_profiles = [payload]
    elif isinstance(payload, list):
        raw_profiles = payload
    else:
        raw_profiles = []
    return [profile for profile in (raw_profiles or []) if isinstance(profile, dict)]


def load_profiles(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        profiles: list[dict[str, Any]] = []
        for profile_file in sorted(path.glob("*.json")):
            profiles.extend(load_profiles(profile_file))
        return profiles

    payload = read_json(path)
    return [normalize_profile(profile) for profile in _raw_profiles(payload)]
