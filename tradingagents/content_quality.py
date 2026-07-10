"""Deterministic quality checks for no-LLM content snapshots."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from tradingagents.content_pilot import read_json


NOISE_PATTERNS = (
    "executive summary",
    "report date",
    "analysis report",
    "comprehensive report",
    "보고서 작성일",
    "종합 기업 분석",
    "투자 제안 보고서",
    "분석 보고서",
    "종합 보고서",
    "분석 대상",
    "대상 종목",
)
REQUIRED_CARD_IDS = ("what_is_it", "why_moved", "composition", "risk", "watch_next")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    return str(value)


def _words(text: str) -> int:
    tokens = re.findall(r"[A-Za-z0-9가-힣]+", text)
    return len(tokens)


def _card_text(card: dict[str, Any]) -> str:
    parts = [
        card.get("headline"),
        card.get("body"),
        card.get("bullets"),
        card.get("bull"),
        card.get("bear"),
    ]
    return _text(parts)


def assess_content_snapshot(content: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    cards = content.get("cards") or []
    visuals = content.get("visuals") or []
    gate = content.get("publish_gate") or {}
    market_data = content.get("market_data") or {}
    composition_data = content.get("composition_data") or {}
    content_type = str(content.get("content_type") or "")
    issues: list[dict[str, Any]] = []
    score = 100

    card_ids = {card.get("id") for card in cards if isinstance(card, dict)}
    for card_id in REQUIRED_CARD_IDS:
        if card_id not in card_ids:
            issues.append({"severity": "error", "code": "missing_card", "card": card_id})
            score -= 12

    for card in cards:
        if not isinstance(card, dict):
            continue
        card_id = str(card.get("id") or "")
        text = _card_text(card)
        lowered = text.lower()
        found_noise = [pattern for pattern in NOISE_PATTERNS if pattern in lowered]
        if found_noise:
            issues.append({
                "severity": "warning",
                "code": "report_metadata_leak",
                "card": card_id,
                "patterns": found_noise[:3],
            })
            score -= 5
        if card.get("status") == "ready" and _words(text) < 3 and card_id != "bull_bear":
            issues.append({"severity": "warning", "code": "thin_ready_card", "card": card_id})
            score -= 4
        if len(str(card.get("body") or "")) > 420:
            issues.append({"severity": "warning", "code": "card_body_too_long", "card": card_id})
            score -= 3

    visual_status = {visual.get("id"): visual.get("status") for visual in visuals if isinstance(visual, dict)}
    if content_type == "stock":
        if not market_data.get("snapshot_file"):
            issues.append({"severity": "warning", "code": "missing_market_snapshot"})
            score -= 8
        if visual_status.get("price_trend") != "ready":
            issues.append({"severity": "warning", "code": "price_trend_not_ready"})
            score -= 8
        if visual_status.get("volume_change") != "ready":
            issues.append({"severity": "warning", "code": "volume_change_not_ready"})
            score -= 8
    elif content_type == "etf":
        missing = [
            field
            for field in ("holdings", "sectors", "countries")
            if not composition_data.get(field)
        ]
        if missing:
            issues.append({"severity": "error", "code": "etf_composition_data_missing", "fields": missing})
            score -= 20
    elif content_type == "theme":
        if not composition_data.get("value_chain"):
            issues.append({"severity": "error", "code": "theme_value_chain_missing"})
            score -= 16
        if not (composition_data.get("domestic_names") or composition_data.get("global_names")):
            issues.append({"severity": "error", "code": "theme_representative_names_missing"})
            score -= 16

    if gate.get("status") != "ready":
        issues.append({"severity": "error", "code": "publish_gate_not_ready", "status": gate.get("status")})
        score -= 20

    errors = sum(1 for issue in issues if issue["severity"] == "error")
    warnings = sum(1 for issue in issues if issue["severity"] == "warning")
    score = max(0, min(100, score))
    if errors:
        status = "fail"
    elif score < 75:
        status = "warn"
    else:
        status = "pass"

    return {
        "source": source,
        "ticker": content.get("ticker"),
        "content_type": content_type,
        "status": status,
        "score": score,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
    }


def audit_content_snapshots(paths: list[Path]) -> dict[str, Any]:
    rows = []
    for path in paths:
        content = read_json(path)
        if content.get("artifact") != "content_snapshot":
            continue
        rows.append(assess_content_snapshot(content, source=str(path)))

    statuses = Counter(row["status"] for row in rows)
    issue_codes = Counter(issue["code"] for row in rows for issue in row["issues"])
    avg_score = round(sum(row["score"] for row in rows) / len(rows), 1) if rows else 0.0
    pass_count = statuses.get("pass", 0)
    return {
        "summary": {
            "snapshots": len(rows),
            "pass": pass_count,
            "pass_pct": round(pass_count / len(rows) * 100, 1) if rows else 0.0,
            "avg_score": avg_score,
            "statuses": dict(statuses),
            "issue_codes": dict(issue_codes),
        },
        "rows": rows,
    }


def find_content_snapshot_files(input_dir: Path) -> list[Path]:
    if input_dir.is_file():
        return [input_dir]
    files = sorted(input_dir.glob("*/content_snapshot.json"))
    if not files and (input_dir / "content_snapshot.json").exists():
        files = [input_dir / "content_snapshot.json"]
    return files
