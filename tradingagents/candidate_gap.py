"""Local-only gap analysis for candidate queue scaling."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _counter_from_ready_rows(rows: list[dict[str, Any]], field: str) -> Counter[str]:
    return Counter(
        str(row.get(field) or "unknown")
        for row in rows
        if row.get("status") == "ready_for_local_pilot"
    )


def _default_type_minimums(target: int) -> dict[str, int]:
    return {
        "stock": max(1, round(target * 0.4)),
        "etf": max(1, round(target * 0.2)),
        "theme": max(1, round(target * 0.2)),
    }


def _default_market_minimums(target: int) -> dict[str, int]:
    return {
        "KR": max(1, round(target * 0.5)),
        "US": max(1, round(target * 0.3)),
    }


def _gaps(current: Counter[str], minimums: dict[str, int]) -> dict[str, dict[str, int]]:
    rows: dict[str, dict[str, int]] = {}
    for key, minimum in minimums.items():
        value = int(current.get(key, 0))
        rows[key] = {
            "current_ready": value,
            "minimum": int(minimum),
            "add_at_least": max(int(minimum) - value, 0),
        }
    return rows


def _required_input(content_type: str) -> str:
    if content_type == "stock":
        return "stock profile or saved report plus Toss/local market snapshot"
    if content_type == "etf":
        return "ETF profile with holdings, sector allocation, and country allocation"
    if content_type == "theme":
        return "theme profile with value chain and domestic/global representative names"
    return "ready profile or saved report with required local data"


def _slot_plan(
    *,
    ready_shortfall: int,
    type_gaps: dict[str, dict[str, int]],
    market_gaps: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    type_pool: list[str] = []
    market_pool: list[str] = []
    for content_type, gap in type_gaps.items():
        type_pool.extend([content_type] * gap["add_at_least"])
    for market, gap in market_gaps.items():
        market_pool.extend([market] * gap["add_at_least"])
    type_pool.extend(["any"] * max(ready_shortfall - len(type_pool), 0))
    market_pool.extend(["any"] * max(ready_shortfall - len(market_pool), 0))

    slots: list[dict[str, Any]] = []
    for index in range(ready_shortfall):
        content_type = type_pool[index] if index < len(type_pool) else "any"
        market = market_pool[index] if index < len(market_pool) else "any"
        input_type = content_type if content_type != "any" else "stock/ETF/theme"
        slots.append({
            "slot": index + 1,
            "preferred_content_type": content_type,
            "preferred_market": market,
            "required_input": _required_input(input_type),
        })
    return slots


def analyze_candidate_gap(
    candidate_queue: dict[str, Any],
    *,
    target_candidates: int | None = None,
    type_minimums: dict[str, int] | None = None,
    market_minimums: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Analyze what is needed before a paid-model comparison gate."""
    if candidate_queue.get("artifact") != "candidate_queue":
        return {
            "schema_version": 1,
            "artifact": "candidate_gap",
            "status": "blocked",
            "reasons": ["candidate_queue_missing_or_invalid"],
            "llm_policy": "no external LLM API; local candidate queue only",
        }

    target = int(target_candidates or candidate_queue.get("target_candidates") or 20)
    rows = [row for row in candidate_queue.get("rows") or [] if isinstance(row, dict)]
    ready_rows = [row for row in rows if row.get("status") == "ready_for_local_pilot"]
    ready = len(ready_rows)
    ready_shortfall = max(target - ready, 0)
    ready_type_counts = _counter_from_ready_rows(rows, "content_type")
    ready_market_counts = _counter_from_ready_rows(rows, "market")
    type_minimums = type_minimums or _default_type_minimums(target)
    market_minimums = market_minimums or _default_market_minimums(target)
    type_gaps = _gaps(ready_type_counts, type_minimums)
    market_gaps = _gaps(ready_market_counts, market_minimums)
    blocked_rows = [
        {
            "ticker": row.get("ticker"),
            "content_type": row.get("content_type"),
            "market": row.get("market"),
            "status": row.get("status"),
            "missing_inputs": row.get("missing_inputs") or [],
        }
        for row in rows
        if row.get("status") != "ready_for_local_pilot"
    ]
    missing_inputs = Counter(
        missing
        for row in blocked_rows
        for missing in row.get("missing_inputs", [])
    )

    reasons: list[str] = []
    if ready_shortfall:
        reasons.append("ready_candidates_below_target")
    if any(gap["add_at_least"] for gap in type_gaps.values()):
        reasons.append("suggested_content_mix_incomplete")
    if any(gap["add_at_least"] for gap in market_gaps.values()):
        reasons.append("suggested_market_mix_incomplete")
    if blocked_rows:
        reasons.append("existing_candidates_need_inputs")

    actions: list[str] = []
    if ready_shortfall:
        actions.append(f"Add {ready_shortfall} more ready local candidates before paid-model comparison.")
    for content_type, gap in type_gaps.items():
        if gap["add_at_least"]:
            actions.append(
                f"Add at least {gap['add_at_least']} {content_type} candidates: {_required_input(content_type)}."
            )
    for market, gap in market_gaps.items():
        if gap["add_at_least"]:
            actions.append(f"Ensure at least {gap['add_at_least']} more ready {market} candidates.")
    for missing, count in sorted(missing_inputs.items()):
        actions.append(f"Complete {missing} for {count} existing queued candidates.")
    if not actions:
        actions.append("Candidate queue is ready for the next local pilot gate.")

    status = "ready" if not reasons else "needs_inputs"
    return {
        "schema_version": 1,
        "artifact": "candidate_gap",
        "status": status,
        "reasons": reasons,
        "llm_policy": "no external LLM API; local candidate queue only",
        "target_candidates": target,
        "summary": {
            "ready_for_local_pilot": ready,
            "ready_shortfall": ready_shortfall,
            "ready_content_types": dict(ready_type_counts),
            "ready_markets": dict(ready_market_counts),
            "blocked_existing_candidates": len(blocked_rows),
            "missing_inputs": dict(missing_inputs),
        },
        "type_gaps": type_gaps,
        "market_gaps": market_gaps,
        "blocked_rows": blocked_rows,
        "actions": actions,
        "slot_plan": _slot_plan(
            ready_shortfall=ready_shortfall,
            type_gaps=type_gaps,
            market_gaps=market_gaps,
        ),
    }


def build_markdown_gap(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Candidate Gap",
        "",
        f"- status: {payload.get('status')}",
        f"- reasons: {', '.join(payload.get('reasons') or []) if payload.get('reasons') else 'none'}",
        f"- llm_policy: {payload.get('llm_policy')}",
        f"- target_candidates: {payload.get('target_candidates')}",
        f"- ready_for_local_pilot: {summary.get('ready_for_local_pilot', 0)}",
        f"- ready_shortfall: {summary.get('ready_shortfall', 0)}",
        f"- ready_content_types: {summary.get('ready_content_types', {})}",
        f"- ready_markets: {summary.get('ready_markets', {})}",
        "",
        "## Actions",
        "",
    ]
    lines.extend(f"- {action}" for action in payload.get("actions") or [])
    lines.extend([
        "",
        "## Slot Plan",
        "",
        "| slot | preferred_type | preferred_market | required_input |",
        "| --- | --- | --- | --- |",
    ])
    for row in payload.get("slot_plan") or []:
        lines.append(
            "| {slot} | {preferred_content_type} | {preferred_market} | {required_input} |".format(
                **row
            )
        )
    if not payload.get("slot_plan"):
        lines.append("| - | - | - | - |")
    lines.append("")
    return "\n".join(lines)


def write_candidate_gap(
    *,
    candidate_queue_path: Path = Path(".pilot/candidates/candidate_queue.json"),
    output_dir: Path = Path(".pilot/candidates"),
    target_candidates: int | None = None,
) -> dict[str, Any]:
    candidate_queue = _read_json(candidate_queue_path)
    payload = analyze_candidate_gap(candidate_queue, target_candidates=target_candidates)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "candidate_gap.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "candidate_gap.md").write_text(
        build_markdown_gap(payload),
        encoding="utf-8",
    )
    return payload
