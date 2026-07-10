"""No-LLM local pilot orchestration for low-cost content validation."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tradingagents.content_pilot import (
    DEFAULT_REPORTS_DIR,
    attach_market_snapshot,
    load_market_snapshot_index,
    run_content_pilot,
)
from tradingagents.content_profiles import final_state_from_profile, load_profiles
from tradingagents.content_quality import audit_content_snapshots
from tradingagents.content_snapshot import build_content_snapshot
from tradingagents.cost_guard import assess_low_cost_config, config_from_env, merge_env
from tradingagents.report_audit import audit_reports


def _safe_pct(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 100, 1)


def _profile_pilot(
    profiles_path: Path | None,
    output_dir: Path | None,
    market_snapshot_dir: Path | None = None,
) -> dict[str, Any]:
    if profiles_path is None:
        return {"status": "skipped", "summary": {}, "rows": [], "reason": "profiles_path_not_set"}
    if not profiles_path.exists():
        return {"status": "skipped", "summary": {}, "rows": [], "reason": "profiles_path_missing"}

    from tradingagents.content_pilot import content_pilot_row, summarize_content_pilot

    rows: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    profiles = load_profiles(profiles_path)
    market_snapshot_index = load_market_snapshot_index(market_snapshot_dir)
    for profile in profiles:
        state, ticker, generated_at = final_state_from_profile(profile)
        attach_market_snapshot(state, ticker, market_snapshot_index)
        content = build_content_snapshot(state, ticker, generated_at)
        row = content_pilot_row(Path(f"{ticker}_{profile.get('profile_type', 'profile')}"), content)
        rows.append(row)
        snapshots.append(content)
        if output_dir:
            target_dir = output_dir / str(ticker).replace("/", "_")
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "content_snapshot.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    summary = summarize_content_pilot(rows)
    payload = {
        "status": "completed",
        "profiles_path": str(profiles_path),
        "market_snapshot_dir": str(market_snapshot_dir) if market_snapshot_dir else None,
        "summary": summary,
        "rows": rows,
    }
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "profile_content_pilot_summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return {**payload, "snapshots": snapshots}


def _gate_status(payload: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    cost = payload["cost_guard"]
    audit = payload["report_audit"]["summary"]
    content = payload["content_pilot"]["summary"]
    quality = payload["content_quality"]["summary"]
    profile = payload["profile_pilot"]
    profile_quality = payload["profile_content_quality"]["summary"]

    if not cost.get("passed"):
        reasons.append("cost_guard_failed")
    if audit.get("reports", 0) == 0:
        reasons.append("no_saved_reports")
    if content.get("reports", 0) == 0:
        reasons.append("no_content_reports")
    if content.get("publish_ready_pct", 0) < 80:
        reasons.append("content_publish_ready_below_80_pct")
    if quality.get("pass_pct", 0) < 80:
        reasons.append("content_quality_pass_below_80_pct")
    if quality.get("avg_score", 0) < 75:
        reasons.append("content_quality_avg_score_below_75")
    if profile.get("status") == "completed" and profile.get("summary", {}).get("publish_ready_pct", 0) < 80:
        reasons.append("profile_publish_ready_below_80_pct")
    if profile.get("status") == "completed" and profile_quality.get("pass_pct", 0) < 80:
        reasons.append("profile_quality_pass_below_80_pct")
    if profile.get("status") == "completed" and profile_quality.get("avg_score", 0) < 75:
        reasons.append("profile_quality_avg_score_below_75")

    if any(reason in reasons for reason in ("cost_guard_failed", "no_saved_reports", "no_content_reports")):
        return "fail", reasons
    if reasons:
        return "warn", reasons
    return "pass", reasons


def build_markdown_report(payload: dict[str, Any]) -> str:
    gate = payload["gate"]
    cost = payload["cost_guard"]
    audit = payload["report_audit"]["summary"]
    content = payload["content_pilot"]["summary"]
    quality = payload["content_quality"]["summary"]
    profile = payload["profile_pilot"]
    profile_quality = payload["profile_content_quality"]["summary"]
    lines = [
        "# Local Pilot Report",
        "",
        f"- status: {gate['status']}",
        f"- reasons: {', '.join(gate['reasons']) if gate['reasons'] else 'none'}",
        f"- llm_policy: {payload['llm_policy']}",
        "",
        "## Cost Guard",
        "",
        f"- status: {cost['status']}",
        f"- score: {cost['score']}/100",
        f"- findings: {', '.join(cost['findings'])}",
        "",
        "## Report Audit",
        "",
        f"- reports: {audit.get('reports', 0)}",
        f"- levels_complete_pct: {audit.get('levels_complete_pct', 0)}",
        f"- avg_content_ready_score: {audit.get('avg_content_ready_score', 0)}",
        f"- warnings: {audit.get('warnings', {})}",
        "",
        "## Content Pilot",
        "",
        f"- reports: {content.get('reports', 0)}",
        f"- publish_ready_pct: {content.get('publish_ready_pct', 0)}",
        f"- market_snapshots_attached: {content.get('market_snapshots_attached', 0)}",
        f"- price_trend_ready: {content.get('price_trend_ready', 0)}",
        f"- volume_change_ready: {content.get('volume_change_ready', 0)}",
        "",
        "## Content Quality",
        "",
        f"- pass_pct: {quality.get('pass_pct', 0)}",
        f"- avg_score: {quality.get('avg_score', 0)}",
        f"- issue_codes: {quality.get('issue_codes', {})}",
        "",
        "## Profile Pilot",
        "",
        f"- status: {profile.get('status')}",
        f"- publish_ready_pct: {profile.get('summary', {}).get('publish_ready_pct', 0)}",
        f"- market_snapshots_attached: {profile.get('summary', {}).get('market_snapshots_attached', 0)}",
        f"- price_trend_ready: {profile.get('summary', {}).get('price_trend_ready', 0)}",
        f"- volume_change_ready: {profile.get('summary', {}).get('volume_change_ready', 0)}",
        "",
        "## Profile Content Quality",
        "",
        f"- pass_pct: {profile_quality.get('pass_pct', 0)}",
        f"- avg_score: {profile_quality.get('avg_score', 0)}",
        f"- issue_codes: {profile_quality.get('issue_codes', {})}",
        "",
    ]
    return "\n".join(lines)


def run_local_pilot(
    *,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    output_dir: Path = Path(".pilot/local"),
    env_file: Path | None = Path(".env.lowcost.example"),
    limit: int | None = 20,
    market_snapshot_dir: Path | None = None,
    profiles_path: Path | None = Path("docs/examples/content_profiles.sample.json"),
    local_only: bool = True,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run a no-LLM local validation bundle and write JSON/Markdown evidence."""
    base_env = dict(os.environ if env is None else env)
    merged = merge_env(base_env, env_file)
    if local_only:
        merged["TRADINGAGENTS_LOCAL_ONLY"] = "true"
    cost_guard = assess_low_cost_config(config_from_env(merged)).to_dict()

    output_dir.mkdir(parents=True, exist_ok=True)
    content_dir = output_dir / "content"
    profile_dir = output_dir / "profiles"

    audit = audit_reports(reports_dir, limit)
    content = run_content_pilot(
        reports_dir,
        limit=limit,
        output_dir=content_dir,
        market_snapshot_dir=market_snapshot_dir,
    )
    content_quality = audit_content_snapshots([
        content_dir / row["report"] / "content_snapshot.json"
        for row in content["rows"]
    ])
    profile = _profile_pilot(profiles_path, profile_dir, market_snapshot_dir)
    if profile.get("status") == "completed":
        profile_content_quality = audit_content_snapshots(
            sorted(profile_dir.glob("*/content_snapshot.json"))
        )
    else:
        profile_content_quality = {
            "summary": {
                "snapshots": 0,
                "pass": 0,
                "pass_pct": 0.0,
                "avg_score": 0.0,
                "statuses": {},
                "issue_codes": {},
            },
            "rows": [],
        }

    payload: dict[str, Any] = {
        "schema_version": 1,
        "artifact": "local_pilot_report",
        "llm_policy": "no external LLM API; local-only config required",
        "reports_dir": str(reports_dir),
        "output_dir": str(output_dir),
        "env_file": str(env_file) if env_file else None,
        "market_snapshot_dir": str(market_snapshot_dir) if market_snapshot_dir else None,
        "profiles_path": str(profiles_path) if profiles_path else None,
        "cost_guard": cost_guard,
        "report_audit": audit,
        "content_pilot": {
            "summary": content["summary"],
            "rows": content["rows"],
        },
        "content_quality": content_quality,
        "profile_pilot": {
            key: value
            for key, value in profile.items()
            if key != "snapshots"
        },
        "profile_content_quality": profile_content_quality,
    }
    gate_status, reasons = _gate_status(payload)
    payload["gate"] = {
        "status": gate_status,
        "reasons": reasons,
        "rule": "local cost guard must pass; saved reports and content pilot must exist; publish and stock/profile content-quality pass rates should stay above 80%.",
    }

    (output_dir / "local_pilot_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "local_pilot_report.md").write_text(
        build_markdown_report(payload),
        encoding="utf-8",
    )
    return payload
