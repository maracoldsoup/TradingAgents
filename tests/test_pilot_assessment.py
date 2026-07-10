import json
from pathlib import Path

import pytest

from tradingagents.pilot_assessment import build_assessment, write_assessment


def _local_report(
    path: Path,
    *,
    gate: str = "pass",
    cost: str = "pass",
    content_reports: int = 5,
    profile_reports: int = 4,
    markets: dict[str, int] | None = None,
    content_types: dict[str, int] | None = None,
) -> Path:
    markets = markets or {"KR": 5, "US": 2}
    content_types = content_types or {"stock": 6, "etf": 1, "theme": 1}
    path.write_text(
        json.dumps({
            "schema_version": 1,
            "artifact": "local_pilot_report",
            "gate": {"status": gate, "reasons": []},
            "cost_guard": {"status": cost, "score": 100},
            "content_pilot": {
                "summary": {
                    "reports": content_reports,
                    "publish_ready_pct": 100.0,
                    "markets": markets,
                    "content_types": {"stock": content_reports},
                    "warnings": {"price_ladder_hidden_incomplete_levels": 2},
                    "market_snapshots_attached": content_reports,
                    "price_trend_ready": content_reports,
                    "volume_change_ready": content_reports,
                }
            },
            "content_quality": {
                "summary": {
                    "pass_pct": 100.0,
                    "avg_score": 100.0,
                    "issue_codes": {},
                }
            },
            "profile_pilot": {
                "summary": {
                    "reports": profile_reports,
                    "publish_ready_pct": 100.0,
                    "markets": markets,
                    "content_types": content_types,
                    "market_snapshots_attached": 1,
                    "price_trend_ready": 1,
                    "volume_change_ready": 1,
                }
            },
            "profile_content_quality": {
                "summary": {
                    "pass_pct": 100.0,
                    "avg_score": 100.0,
                    "issue_codes": {},
                }
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.mark.unit
def test_build_assessment_recommends_constrained_local_continuation(tmp_path):
    report = _local_report(tmp_path / "local_pilot_report.json", content_reports=5)

    payload = build_assessment([report], target_candidates=20)

    assert payload["artifact"] == "pilot_assessment"
    assert payload["llm_policy"].startswith("no external LLM")
    assert payload["verdict"]["status"] == "continue_with_constraints"
    assert "candidate_count_too_small_for_scale_decision" in payload["verdict"]["reasons"]
    assert payload["verdict"]["twelve_month_validation"]["required_now"] is False
    assert payload["aggregate"]["totals"]["market_snapshots_attached"] == 6
    assert payload["aggregate"]["coverage"]["content_types"]["etf"] == 1
    assert payload["aggregate"]["coverage"]["content_types"]["theme"] == 1


@pytest.mark.unit
def test_build_assessment_blocks_when_cost_guard_failed(tmp_path):
    report = _local_report(tmp_path / "local_pilot_report.json", cost="fail")

    payload = build_assessment([report], target_candidates=5)

    assert payload["verdict"]["status"] == "blocked"
    assert "cost_guard_failed" in payload["verdict"]["blockers"]


@pytest.mark.unit
def test_build_assessment_uses_candidate_queue_ready_count_when_available(tmp_path):
    report = _local_report(tmp_path / "local_pilot_report.json", content_reports=20)
    queue = tmp_path / "candidate_queue.json"
    queue.write_text(
        json.dumps({
            "schema_version": 1,
            "artifact": "candidate_queue",
            "summary": {
                "candidates": 9,
                "ready_for_local_pilot": 9,
                "remaining_ready_to_target": 11,
                "markets": {"KR": 6, "US": 3},
                "content_types": {"stock": 4, "etf": 3, "theme": 2},
            },
            "gate": {
                "status": "needs_more_candidates",
                "reasons": ["ready_candidates_below_target"],
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = build_assessment([report], target_candidates=20, candidate_queue_path=queue)

    assert payload["candidate_queue"]["path"] == str(queue)
    assert payload["verdict"]["ready_candidates_used"] == 9
    assert payload["verdict"]["candidate_count_source"] == "candidate_queue"
    assert "candidate_count_too_small_for_scale_decision" in payload["verdict"]["reasons"]


@pytest.mark.unit
def test_write_assessment_writes_json_and_markdown(tmp_path):
    report = _local_report(tmp_path / "local_pilot_report.json", content_reports=20)

    payload = write_assessment([report], output_dir=tmp_path / "out", target_candidates=20)

    assert payload["verdict"]["status"] == "continue_with_constraints"
    assert (tmp_path / "out" / "pilot_assessment.json").exists()
    markdown = (tmp_path / "out" / "pilot_assessment.md").read_text(encoding="utf-8")
    assert "# Pilot Assessment" in markdown
    assert "12개월 검증은 지금 단계에서는 과하다" in markdown
