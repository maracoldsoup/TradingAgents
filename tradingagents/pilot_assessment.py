"""Deterministic local-only assessment for the content pilot."""

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


def _summary(report: dict[str, Any], key: str) -> dict[str, Any]:
    value = report.get(key) or {}
    summary = value.get("summary") if isinstance(value, dict) else None
    return summary if isinstance(summary, dict) else {}


def _counter_add(target: Counter[str], source: dict[str, Any] | None) -> None:
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        try:
            target[str(key)] += int(value)
        except (TypeError, ValueError):
            continue


def _safe_min(values: list[float], default: float = 0.0) -> float:
    return min(values) if values else default


def _safe_avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_candidate_queue(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = _read_json(path)
    if payload.get("artifact") != "candidate_queue":
        return None
    return {
        "path": str(path),
        "summary": payload.get("summary") or {},
        "gate": payload.get("gate") or {},
    }


def aggregate_local_reports(report_paths: list[Path]) -> dict[str, Any]:
    """Aggregate existing local pilot reports without API or LLM calls."""
    rows: list[dict[str, Any]] = []
    markets: Counter[str] = Counter()
    content_types: Counter[str] = Counter()
    gate_statuses: Counter[str] = Counter()
    issue_codes: Counter[str] = Counter()
    warning_codes: Counter[str] = Counter()

    max_saved_reports = 0
    total_profile_reports = 0
    total_market_snapshots = 0
    total_price_trend_ready = 0
    total_volume_change_ready = 0
    content_publish_pcts: list[float] = []
    content_quality_pcts: list[float] = []
    profile_publish_pcts: list[float] = []
    profile_quality_pcts: list[float] = []
    quality_scores: list[float] = []
    cost_statuses: Counter[str] = Counter()

    for path in report_paths:
        report = _read_json(path)
        if report.get("artifact") != "local_pilot_report":
            rows.append({"path": str(path), "status": "ignored", "reason": "not_local_pilot_report"})
            continue

        content = _summary(report, "content_pilot")
        content_quality = _summary(report, "content_quality")
        profile = _summary(report, "profile_pilot")
        profile_quality = _summary(report, "profile_content_quality")
        gate = report.get("gate") or {}
        cost = report.get("cost_guard") or {}

        max_saved_reports = max(max_saved_reports, int(content.get("reports", 0) or 0))
        total_profile_reports += int(profile.get("reports", 0) or 0)
        total_market_snapshots += int(content.get("market_snapshots_attached", 0) or 0)
        total_market_snapshots += int(profile.get("market_snapshots_attached", 0) or 0)
        total_price_trend_ready += int(content.get("price_trend_ready", 0) or 0)
        total_price_trend_ready += int(profile.get("price_trend_ready", 0) or 0)
        total_volume_change_ready += int(content.get("volume_change_ready", 0) or 0)
        total_volume_change_ready += int(profile.get("volume_change_ready", 0) or 0)

        content_publish_pcts.append(_number(content.get("publish_ready_pct")))
        content_quality_pcts.append(_number(content_quality.get("pass_pct")))
        quality_scores.append(_number(content_quality.get("avg_score")))
        if profile:
            profile_publish_pcts.append(_number(profile.get("publish_ready_pct")))
        if profile_quality:
            profile_quality_pcts.append(_number(profile_quality.get("pass_pct")))
            quality_scores.append(_number(profile_quality.get("avg_score")))

        _counter_add(markets, content.get("markets"))
        _counter_add(markets, profile.get("markets"))
        _counter_add(content_types, content.get("content_types"))
        _counter_add(content_types, profile.get("content_types"))
        _counter_add(issue_codes, content_quality.get("issue_codes"))
        _counter_add(issue_codes, profile_quality.get("issue_codes"))
        _counter_add(warning_codes, content.get("warnings"))
        _counter_add(warning_codes, profile.get("warnings"))
        gate_statuses[str(gate.get("status") or "missing")] += 1
        cost_statuses[str(cost.get("status") or "missing")] += 1

        rows.append({
            "path": str(path),
            "status": "included",
            "gate": gate.get("status"),
            "cost_guard": cost.get("status"),
            "content_reports": content.get("reports", 0),
            "profile_reports": profile.get("reports", 0),
            "content_publish_ready_pct": content.get("publish_ready_pct", 0),
            "content_quality_pass_pct": content_quality.get("pass_pct", 0),
            "profile_publish_ready_pct": profile.get("publish_ready_pct", 0),
            "profile_quality_pass_pct": profile_quality.get("pass_pct", 0),
        })

    included = sum(1 for row in rows if row["status"] == "included")
    return {
        "reports_included": included,
        "rows": rows,
        "totals": {
            "saved_stock_reports": max_saved_reports,
            "profile_reports": total_profile_reports,
            "candidate_paths": max_saved_reports + total_profile_reports,
            "market_snapshots_attached": total_market_snapshots,
            "price_trend_ready": total_price_trend_ready,
            "volume_change_ready": total_volume_change_ready,
        },
        "coverage": {
            "markets": dict(markets),
            "content_types": dict(content_types),
            "gate_statuses": dict(gate_statuses),
            "cost_statuses": dict(cost_statuses),
            "issue_codes": dict(issue_codes),
            "warnings": dict(warning_codes),
        },
        "quality": {
            "min_content_publish_ready_pct": _safe_min(content_publish_pcts),
            "min_content_quality_pass_pct": _safe_min(content_quality_pcts),
            "min_profile_publish_ready_pct": _safe_min(profile_publish_pcts),
            "min_profile_quality_pass_pct": _safe_min(profile_quality_pcts),
            "avg_quality_score": _safe_avg(quality_scores),
        },
    }


def _verdict(
    aggregate: dict[str, Any],
    *,
    target_candidates: int,
    candidate_queue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    totals = aggregate["totals"]
    queue_summary = candidate_queue.get("summary", {}) if candidate_queue else {}
    queue_gate = candidate_queue.get("gate", {}) if candidate_queue else {}
    coverage = aggregate["coverage"]
    content_types = queue_summary.get("content_types") or coverage["content_types"]
    markets = queue_summary.get("markets") or coverage["markets"]
    quality = aggregate["quality"]
    reasons: list[str] = []
    blockers: list[str] = []
    next_checks: list[str] = []
    ready_candidates = int(queue_summary.get("ready_for_local_pilot", totals["candidate_paths"]) or 0)

    if aggregate["reports_included"] == 0:
        blockers.append("no_local_pilot_reports")
    if coverage["cost_statuses"].get("fail"):
        blockers.append("cost_guard_failed")
    if coverage["gate_statuses"].get("fail"):
        blockers.append("local_pilot_gate_failed")
    if queue_gate.get("status") == "blocked":
        blockers.append("candidate_queue_blocked")
    if quality["min_content_quality_pass_pct"] < 80:
        blockers.append("content_quality_below_80_pct")

    if ready_candidates < target_candidates:
        reasons.append("candidate_count_too_small_for_scale_decision")
        next_checks.append(f"saved_report_or_profile_candidates_{target_candidates}_plus")
    if content_types.get("etf", 0) == 0:
        reasons.append("etf_path_not_covered")
        next_checks.append("real_etf_holdings_csv_import")
    if content_types.get("theme", 0) == 0:
        reasons.append("theme_path_not_covered")
        next_checks.append("real_theme_value_chain_csv_import")
    if markets.get("US", 0) == 0:
        reasons.append("overseas_path_not_covered")
        next_checks.append("overseas_stock_or_etf_profile_with_market_snapshot")
    if coverage["issue_codes"]:
        reasons.append("content_quality_issues_present")
    if coverage["warnings"]:
        reasons.append("non_blocking_visual_warnings_present")

    if blockers:
        status = "blocked"
        recommendation = "Do not spend external LLM tokens yet; fix local blockers first."
    elif reasons:
        status = "continue_with_constraints"
        recommendation = "Continue local-only, but validate more real candidates before paid-model work."
    else:
        status = "continue"
        recommendation = "Continue local-only and prepare a narrow paid-model comparison only after audience/content checks."

    return {
        "status": status,
        "recommendation": recommendation,
        "blockers": blockers,
        "reasons": reasons,
        "next_checks": sorted(set(next_checks)),
        "ready_candidates_used": ready_candidates,
        "candidate_count_source": "candidate_queue" if candidate_queue else "local_pilot_paths",
        "twelve_month_validation": {
            "required_now": False,
            "judgment": "12개월 검증은 지금 단계에서는 과하다. 콘텐츠 MVP는 설명 구조, 데이터 출처, 시각화 반복 생산성이 먼저이고, 12개월 검증은 자동매매 성과나 정량 랭킹을 주장할 때 좁은 후보군에만 붙이는 편이 낫다.",
        },
    }


def build_assessment(
    report_paths: list[Path],
    *,
    target_candidates: int = 20,
    candidate_queue_path: Path | None = None,
) -> dict[str, Any]:
    aggregate = aggregate_local_reports(report_paths)
    candidate_queue = load_candidate_queue(candidate_queue_path)
    verdict = _verdict(
        aggregate,
        target_candidates=target_candidates,
        candidate_queue=candidate_queue,
    )
    return {
        "schema_version": 1,
        "artifact": "pilot_assessment",
        "llm_policy": "no external LLM API; reads existing local JSON reports only",
        "target_candidates": target_candidates,
        "verdict": verdict,
        "aggregate": aggregate,
        "candidate_queue": candidate_queue,
        "free_first_path": [
            "Use Toss read-only snapshots for stock metadata, prices, candles, FX, and market calendars.",
            "Use local ETF holdings CSV/JSON imports for holdings, sector, and country composition.",
            "Use local theme-map CSV/JSON imports for value-chain and representative-name composition.",
            "Keep Ollama/local-only config for drafting and deterministic snapshot builders for publishing checks.",
            "Reserve Gemini or other paid LLMs for a later A/B sample after 20-30 real candidates pass local quality gates.",
        ],
        "hard_truths": [
            "The current evidence supports a content-product pilot, not an investment-performance claim.",
            "Toss is useful for domestic and US stock market data, but not enough for ETF holdings or theme taxonomy.",
            "Sample ETF/theme profiles prove the pipeline, but real provider files are still needed.",
            "A 12-month validation run before the content format is proven would likely burn tokens without answering the product question.",
        ],
    }


def build_markdown_assessment(payload: dict[str, Any]) -> str:
    verdict = payload["verdict"]
    aggregate = payload["aggregate"]
    totals = aggregate["totals"]
    coverage = aggregate["coverage"]
    quality = aggregate["quality"]
    lines = [
        "# Pilot Assessment",
        "",
        f"- status: {verdict['status']}",
        f"- recommendation: {verdict['recommendation']}",
        f"- llm_policy: {payload['llm_policy']}",
        f"- target_candidates: {payload['target_candidates']}",
        f"- ready_candidates_used: {verdict['ready_candidates_used']}",
        f"- candidate_count_source: {verdict['candidate_count_source']}",
        "",
        "## Current Evidence",
        "",
        f"- local_reports_included: {aggregate['reports_included']}",
        f"- saved_stock_reports: {totals['saved_stock_reports']}",
        f"- profile_reports: {totals['profile_reports']}",
        f"- candidate_paths: {totals['candidate_paths']}",
        f"- market_snapshots_attached: {totals['market_snapshots_attached']}",
        f"- price_trend_ready: {totals['price_trend_ready']}",
        f"- volume_change_ready: {totals['volume_change_ready']}",
        f"- markets: {coverage['markets']}",
        f"- content_types: {coverage['content_types']}",
        f"- min_content_quality_pass_pct: {quality['min_content_quality_pass_pct']}",
        f"- min_profile_quality_pass_pct: {quality['min_profile_quality_pass_pct']}",
        f"- avg_quality_score: {quality['avg_quality_score']}",
        "",
    ]
    if payload.get("candidate_queue"):
        queue = payload["candidate_queue"]
        queue_summary = queue.get("summary", {})
        queue_gate = queue.get("gate", {})
        lines.extend([
            "## Candidate Queue",
            "",
            f"- path: {queue.get('path')}",
            f"- status: {queue_gate.get('status')}",
            f"- reasons: {queue_gate.get('reasons', [])}",
            f"- candidates: {queue_summary.get('candidates', 0)}",
            f"- ready_for_local_pilot: {queue_summary.get('ready_for_local_pilot', 0)}",
            f"- remaining_ready_to_target: {queue_summary.get('remaining_ready_to_target', 0)}",
            "",
        ])
    lines.extend([
        "## Hard Truths",
        "",
    ])
    lines.extend(f"- {item}" for item in payload["hard_truths"])
    lines.extend([
        "",
        "## Free First Path",
        "",
    ])
    lines.extend(f"- {item}" for item in payload["free_first_path"])
    lines.extend([
        "",
        "## 12-Month Validation",
        "",
        f"- required_now: {verdict['twelve_month_validation']['required_now']}",
        f"- judgment: {verdict['twelve_month_validation']['judgment']}",
        "",
        "## Next Checks",
        "",
    ])
    if verdict["next_checks"]:
        lines.extend(f"- {item}" for item in verdict["next_checks"])
    else:
        lines.append("- none")
    if verdict["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in verdict["blockers"])
    if verdict["reasons"]:
        lines.extend(["", "## Reasons", ""])
        lines.extend(f"- {item}" for item in verdict["reasons"])
    lines.append("")
    return "\n".join(lines)


def write_assessment(
    report_paths: list[Path],
    *,
    output_dir: Path = Path(".pilot/assessment"),
    target_candidates: int = 20,
    candidate_queue_path: Path | None = None,
) -> dict[str, Any]:
    payload = build_assessment(
        report_paths,
        target_candidates=target_candidates,
        candidate_queue_path=candidate_queue_path,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pilot_assessment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "pilot_assessment.md").write_text(
        build_markdown_assessment(payload),
        encoding="utf-8",
    )
    return payload
