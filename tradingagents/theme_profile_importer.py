"""Import local theme map files into structured no-LLM profile JSON."""

from __future__ import annotations

import csv
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

from tradingagents.content_profiles import normalize_theme_profile


_COLUMN_ALIASES = {
    "stage": ("stage", "value chain stage", "밸류체인", "단계", "구간"),
    "description": ("description", "stage description", "설명", "단계 설명"),
    "scope": ("scope", "group", "type", "구분", "국내/해외"),
    "ticker": ("ticker", "symbol", "종목코드", "티커"),
    "name": ("name", "company", "company name", "종목명", "이름"),
    "role": ("role", "position", "역할"),
    "market": ("market", "exchange", "시장", "거래소"),
    "country": ("country", "location", "국가", "지역"),
    "catalysts": ("catalysts", "catalyst", "driver", "촉매", "상승 촉매"),
    "risks": ("risks", "risk", "리스크", "위험"),
    "metrics": ("metrics", "metric", "key metric", "핵심 지표", "지표"),
}

_DOMESTIC_MARKERS = ("domestic", "korea", "south korea", "kr", "한국", "국내", "kospi", "kosdaq", "ksc")
_GLOBAL_MARKERS = ("global", "overseas", "us", "usa", "united states", "china", "taiwan", "japan", "해외", "nasdaq", "nyse")


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


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_theme_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        return _read_csv(path)
    payload = _read_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        if payload.get("profile_type") == "theme":
            return list(payload.get("value_chain") or [])
        rows = payload.get("rows") or payload.get("data") or payload.get("value_chain")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _split_values(value: str) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    parts = re.split(r"[;\n|]+", text)
    return [part.strip() for part in parts if part.strip()]


def _classification(row: dict[str, Any]) -> str:
    text = " ".join(
        _first(row, field).lower()
        for field in ("scope", "market", "country")
        if _first(row, field)
    )
    if any(marker in text for marker in _DOMESTIC_MARKERS):
        return "domestic"
    if any(marker in text for marker in _GLOBAL_MARKERS):
        return "global"
    return "global"


def _name_row(row: dict[str, Any], stage: str) -> dict[str, Any]:
    ticker = _first(row, "ticker")
    name = _first(row, "name") or ticker
    if not (ticker or name):
        return {}
    payload: dict[str, Any] = {}
    if ticker:
        payload["ticker"] = ticker
    if name:
        payload["name"] = name
    for field in ("role", "market", "country"):
        value = _first(row, field)
        if value:
            payload[field] = value
    if stage:
        payload["stage"] = stage
    return payload


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (
            str(row.get("ticker") or "").upper(),
            str(row.get("name") or ""),
            str(row.get("stage") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _named_items(values: list[str]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append({"name": value})
    return result


def import_theme_profile(
    *,
    theme_map_path: Path,
    ticker: str,
    name: str | None = None,
    description: str | None = None,
    as_of: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Build a normalized theme profile from a local CSV/JSON map file."""
    rows = load_theme_rows(theme_map_path)
    stages: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    domestic_names: list[dict[str, Any]] = []
    global_names: list[dict[str, Any]] = []
    catalysts: list[str] = []
    risks: list[str] = []

    for row in rows:
        stage = _first(row, "stage")
        if not stage and isinstance(row.get("stage"), str):
            stage = _clean_text(row["stage"])
        if not stage:
            continue
        stage_payload = stages.setdefault(
            stage,
            {
                "stage": stage,
                "description": _first(row, "description"),
                "domestic_names": [],
                "global_names": [],
                "metrics": [],
            },
        )
        if not stage_payload.get("description"):
            stage_payload["description"] = _first(row, "description")

        name_payload = _name_row(row, stage)
        if name_payload:
            if _classification(row) == "domestic":
                stage_payload["domestic_names"].append(name_payload)
                domestic_names.append(name_payload)
            else:
                stage_payload["global_names"].append(name_payload)
                global_names.append(name_payload)

        for metric in _split_values(_first(row, "metrics")):
            stage_payload["metrics"].append({"name": metric})
        catalysts.extend(_split_values(_first(row, "catalysts")))
        risks.extend(_split_values(_first(row, "risks")))

    value_chain = []
    for stage_payload in stages.values():
        clean_stage = {
            key: value
            for key, value in {
                "stage": stage_payload["stage"],
                "description": stage_payload.get("description"),
                "domestic_names": _dedupe(stage_payload.get("domestic_names") or []),
                "global_names": _dedupe(stage_payload.get("global_names") or []),
                "metrics": _named_items([
                    str(item.get("name"))
                    for item in stage_payload.get("metrics") or []
                    if item.get("name")
                ]),
            }.items()
            if value not in (None, "", [])
        }
        value_chain.append(clean_stage)

    profile = {
        "profile_type": "theme",
        "ticker": ticker,
        "name": name or ticker,
        "description": description,
        "as_of": as_of,
        "source": source or f"local_file:{theme_map_path.name}",
        "value_chain": value_chain,
        "domestic_names": _dedupe(domestic_names),
        "global_names": _dedupe(global_names),
        "catalysts": _named_items(catalysts),
        "risks": _named_items(risks),
    }
    return normalize_theme_profile(profile)

