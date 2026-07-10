"""Public service asset model built from local content snapshots."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SNAPSHOT_FILE = "content_snapshot.json"
PUBLIC_SOURCE_FALLBACK = {
    "market_data": "market_data_cache",
    "composition": "structured_profile",
    "content": "local_content_snapshot",
}


def _clean_text(value: Any, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    if limit is not None and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "..."
    return text


def _slug(value: str) -> str:
    raw = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9가-힣]+", "-", raw)
    return slug.strip("-") or "asset"


def asset_id(kind: str, ticker: str) -> str:
    """Return a stable public asset id."""
    return f"{_slug(kind)}-{_slug(ticker)}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def find_snapshot_files(input_dirs: Iterable[Path]) -> list[Path]:
    """Find content snapshot files without exposing paths to public models."""
    files: list[Path] = []
    seen: set[Path] = set()
    for input_dir in input_dirs:
        path = Path(input_dir)
        candidates = [path] if path.is_file() else sorted(path.glob(f"*/{SNAPSHOT_FILE}"))
        if path.is_dir() and (path / SNAPSHOT_FILE).exists():
            candidates.insert(0, path / SNAPSHOT_FILE)
        for candidate in candidates:
            if candidate.name != SNAPSHOT_FILE:
                continue
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(candidate)
    return files


def _card(content: dict[str, Any], card_id: str) -> dict[str, Any]:
    for card in content.get("cards") or []:
        if isinstance(card, dict) and card.get("id") == card_id:
            return card
    return {}


def _card_block(card: dict[str, Any], *, limit: int = 280) -> dict[str, Any]:
    bullets = card.get("bullets") if isinstance(card.get("bullets"), list) else []
    body = card.get("body") or card.get("headline") or " ".join(str(item) for item in bullets[:3])
    return {
        "title": _clean_text(card.get("title")),
        "status": _clean_text(card.get("status") or "missing"),
        "summary": _clean_text(body, limit),
        "bullets": [_clean_text(item, 180) for item in bullets[:5] if _clean_text(item)],
    }


def _points(card: dict[str, Any], key: str) -> list[str]:
    stance = card.get(key) if isinstance(card.get(key), dict) else {}
    bullets = stance.get("bullets") if isinstance(stance.get("bullets"), list) else []
    if bullets:
        return [_clean_text(item, 160) for item in bullets[:5] if _clean_text(item)]
    text = stance.get("body") or stance.get("headline")
    return [_clean_text(text, 180)] if _clean_text(text) else []


def _row(row: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    clean = {key: row.get(key) for key in keys if row.get(key) not in (None, "")}
    return clean


def _rows(rows: Any, keys: tuple[str, ...], limit: int = 20) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [clean for clean in (_row(row, keys) for row in rows[:limit]) if clean]


def _theme_stage(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    stage = _row(row, ("stage", "name", "description"))
    stage["domestic_names"] = _rows(row.get("domestic_names"), ("ticker", "name", "role", "market"), 12)
    stage["global_names"] = _rows(row.get("global_names"), ("ticker", "name", "role", "market"), 12)
    return {key: value for key, value in stage.items() if value not in (None, "", [])}


def _composition(content: dict[str, Any]) -> dict[str, Any]:
    data = content.get("composition_data") if isinstance(content.get("composition_data"), dict) else {}
    kind = str(content.get("content_type") or data.get("profile_type") or "stock").lower()
    block = _card_block(_card(content, "composition"), limit=360)
    result: dict[str, Any] = {
        "summary": block["summary"],
        "status": block["status"],
    }
    if kind == "etf":
        result.update({
            "holdings": _rows(data.get("holdings"), ("ticker", "name", "sector", "country", "weight_pct"), 15),
            "sectors": _rows(data.get("sectors"), ("name", "weight_pct"), 12),
            "countries": _rows(data.get("countries"), ("name", "weight_pct"), 12),
            "expense_ratio_pct": data.get("expense_ratio_pct"),
            "aum": data.get("aum"),
            "benchmark": data.get("benchmark"),
            "issuer": data.get("issuer"),
        })
    elif kind == "theme":
        stages = [_theme_stage(row) for row in (data.get("value_chain") or [])[:12]]
        result.update({
            "description": _clean_text(data.get("description"), 240),
            "value_chain": [stage for stage in stages if stage],
            "domestic_names": _rows(data.get("domestic_names"), ("ticker", "name", "role", "market"), 20),
            "global_names": _rows(data.get("global_names"), ("ticker", "name", "role", "market"), 20),
            "catalysts": _rows(data.get("catalysts"), ("name", "description"), 12),
            "risks": _rows(data.get("risks"), ("name", "description"), 12),
        })
    else:
        result.update({
            "business_lines": _rows(data.get("business_lines"), ("name", "weight_pct", "description"), 12),
            "regions": _rows(data.get("regions"), ("name", "weight_pct", "description"), 12),
            "products": _rows(data.get("products"), ("name", "description"), 12),
            "peers": _rows(data.get("peers"), ("ticker", "name", "market"), 12),
            "sector": data.get("sector"),
            "industry": data.get("industry"),
            "exchange": data.get("exchange"),
        })
    return {key: value for key, value in result.items() if value not in (None, "", [])}


def _public_source_label(value: Any, fallback: str) -> str:
    label = _clean_text(value, 80)
    lowered = label.lower()
    if not label:
        return fallback
    if "/" in label or "\\" in label or lowered.endswith((".json", ".csv", ".md")):
        return fallback
    if label.startswith("."):
        return fallback
    return label


def _sources(content: dict[str, Any]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    market = content.get("market_data") if isinstance(content.get("market_data"), dict) else {}
    composition = content.get("composition_data") if isinstance(content.get("composition_data"), dict) else {}
    if market:
        sources.append({
            "kind": "market_data",
            "label": _public_source_label(market.get("source"), PUBLIC_SOURCE_FALLBACK["market_data"]),
        })
    if composition:
        sources.append({
            "kind": "composition",
            "label": _public_source_label(composition.get("source"), PUBLIC_SOURCE_FALLBACK["composition"]),
        })
    if not sources:
        sources.append({"kind": "content", "label": PUBLIC_SOURCE_FALLBACK["content"]})
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        key = (source["kind"], source["label"])
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _review(content: dict[str, Any]) -> dict[str, Any]:
    market = content.get("market_data") if isinstance(content.get("market_data"), dict) else {}
    metrics = market.get("metrics") if isinstance(market.get("metrics"), dict) else {}
    tracked_keys = (
        "return_1d_pct",
        "return_5d_pct",
        "return_20d_pct",
        "volume_vs_20d_avg",
    )
    clean_metrics = {
        key: value
        for key in tracked_keys
        if (value := _number(metrics.get(key))) is not None
    }
    why = _card_block(_card(content, "why_moved"), limit=220)
    if clean_metrics:
        status = "available"
        note = "local market metrics available"
    else:
        status = "pending"
        note = "market metrics pending"
    return {
        "status": status,
        "published_at": _clean_text(content.get("trade_date") or content.get("generated_at")),
        "basis": why["summary"],
        "metrics": clean_metrics,
        "note": note,
    }


def _visuals(content: dict[str, Any]) -> list[dict[str, Any]]:
    visuals = []
    for visual in content.get("visuals") or []:
        if not isinstance(visual, dict):
            continue
        visuals.append({
            "id": _clean_text(visual.get("id")),
            "title": _clean_text(visual.get("title")),
            "type": _clean_text(visual.get("type")),
            "status": _clean_text(visual.get("status") or "missing"),
            "data_required": [
                _clean_text(item)
                for item in (visual.get("data_required") or [])[:8]
                if _clean_text(item)
            ],
        })
    return visuals


def _name(content: dict[str, Any]) -> str:
    data = content.get("composition_data") if isinstance(content.get("composition_data"), dict) else {}
    ticker = _clean_text(content.get("ticker"))
    for candidate in (data.get("name"), content.get("name")):
        name = _clean_text(candidate)
        if name and name != ticker:
            return name
    extracted = _name_from_cards(content, ticker)
    return extracted or ticker


def _name_from_cards(content: dict[str, Any], ticker: str) -> str:
    if not ticker:
        return ""
    escaped_ticker = re.escape(ticker)
    compact_ticker = re.escape(ticker.split(".")[0])
    korean_pattern = rf"([가-힣][가-힣A-Za-z0-9&.·-]{{1,30}})\s*\([^)]*(?:{escaped_ticker}|{compact_ticker})[^)]*\)"
    english_pattern = rf"{escaped_ticker}\s*[은는]\s*([A-Z][A-Za-z0-9&.,\s-]{{2,60}}?)입니다"
    texts = []
    for card in content.get("cards") or []:
        if not isinstance(card, dict):
            continue
        texts.extend([card.get("headline"), card.get("body")])
        texts.extend(card.get("bullets") or [])
    for pattern in (korean_pattern, english_pattern):
        for text in texts:
            haystack = _clean_text(text, 1000)
            match = re.search(pattern, haystack)
            if not match:
                continue
            name = _clean_text(match.group(1), 48)
            name = re.sub(r"^(대상\s*종목|분석\s*대상|종목)\s*[:：-]?\s*", "", name).strip()
            name = re.sub(r"^\d+\.\s*", "", name).strip()
            if name and name != ticker and len(name) >= 2:
                return name
    return ""


def asset_from_snapshot(content: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a content snapshot to a public-facing asset dict."""
    if content.get("artifact") != "content_snapshot":
        return None
    ticker = _clean_text(content.get("ticker"))
    if not ticker:
        return None
    kind = _clean_text(content.get("content_type") or content.get("asset_type") or "stock").lower()
    if kind not in {"stock", "etf", "theme", "crypto"}:
        kind = "stock"
    data = content.get("composition_data") if isinstance(content.get("composition_data"), dict) else {}
    gate = content.get("publish_gate") if isinstance(content.get("publish_gate"), dict) else {}
    bull_bear = _card(content, "bull_bear")
    risk = _card_block(_card(content, "risk"), limit=260)
    watch = _card_block(_card(content, "watch_next"), limit=260)

    return {
        "id": asset_id(kind, ticker),
        "kind": kind,
        "ticker": ticker,
        "name": _name(content),
        "market": _clean_text(content.get("market_adapter") or data.get("market") or data.get("country")),
        "one_liner": _card_block(_card(content, "what_is_it"), limit=260),
        "why_moved": _card_block(_card(content, "why_moved"), limit=300),
        "composition": _composition(content),
        "bull_points": _points(bull_bear, "bull"),
        "bear_points": _points(bull_bear, "bear"),
        "risk_points": risk["bullets"] or ([risk["summary"]] if risk["summary"] else []),
        "watch_points": watch["bullets"] or ([watch["summary"]] if watch["summary"] else []),
        "visuals": _visuals(content),
        "sources": _sources(content),
        "review": _review(content),
        "as_of": _clean_text(data.get("as_of") or content.get("trade_date") or content.get("generated_at")),
        "publish_status": _clean_text(gate.get("status") or "draft"),
    }


def load_assets(input_dirs: Iterable[Path]) -> list[dict[str, Any]]:
    """Load public assets from content snapshot directories."""
    assets = []
    seen: set[str] = set()
    for path in find_snapshot_files(input_dirs):
        asset = asset_from_snapshot(_read_json(path))
        if not asset or asset["id"] in seen:
            continue
        seen.add(asset["id"])
        assets.append(asset)
    return assets


def find_asset(assets: Iterable[dict[str, Any]], asset_id_value: str) -> dict[str, Any] | None:
    """Find an asset by public id."""
    for asset in assets:
        if asset.get("id") == asset_id_value:
            return asset
    return None


def theme_assets(assets: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return public theme assets."""
    return [asset for asset in assets if asset.get("kind") == "theme"]
