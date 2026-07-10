import json

import pytest

from tradingagents.pilot_dashboard import render_pilot_dashboard


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.unit
def test_render_pilot_dashboard_combines_local_artifacts(tmp_path):
    local_pilot = _write_json(
        tmp_path / "local_pilot_report.json",
        {
            "artifact": "local_pilot_report",
            "gate": {"status": "pass"},
            "cost_guard": {"status": "pass", "score": 100},
            "content_pilot": {
                "summary": {
                    "reports": 5,
                    "publish_ready_pct": 100,
                    "market_snapshots_attached": 5,
                    "price_trend_ready": 5,
                    "warnings": {"price_ladder_hidden_incomplete_levels": 4},
                }
            },
            "content_quality": {"summary": {"pass_pct": 100}},
            "profile_pilot": {"summary": {"reports": 4, "publish_ready_pct": 100}},
            "profile_content_quality": {"summary": {"pass_pct": 100}},
        },
    )
    queue = _write_json(
        tmp_path / "candidate_queue.json",
        {
            "artifact": "candidate_queue",
            "target_candidates": 20,
            "summary": {
                "ready_for_local_pilot": 9,
                "markets": {"KR": 6, "US": 3},
                "content_types": {"stock": 4, "etf": 3, "theme": 2},
                "missing_inputs": {},
            },
            "gate": {"status": "needs_more_candidates"},
            "rows": [
                {
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "content_type": "stock",
                    "market": "US",
                    "status": "ready_for_local_pilot",
                    "missing_inputs": [],
                    "source_types": ["profile"],
                }
            ],
        },
    )
    gap = _write_json(
        tmp_path / "candidate_gap.json",
        {
            "artifact": "candidate_gap",
            "status": "needs_inputs",
            "summary": {"ready_shortfall": 11},
            "type_gaps": {
                "stock": {"current_ready": 4, "minimum": 8},
                "etf": {"current_ready": 3, "minimum": 4},
            },
            "market_gaps": {"KR": {"current_ready": 6, "minimum": 10}},
            "actions": ["Add 11 more ready local candidates before paid-model comparison."],
            "slot_plan": [
                {
                    "slot": 1,
                    "preferred_content_type": "stock",
                    "preferred_market": "KR",
                    "required_input": "stock profile or saved report plus Toss/local market snapshot",
                }
            ],
        },
    )
    assessment = _write_json(
        tmp_path / "pilot_assessment.json",
        {
            "artifact": "pilot_assessment",
            "verdict": {
                "status": "continue_with_constraints",
                "candidate_count_source": "candidate_queue",
            },
        },
    )
    input_review = _write_json(
        tmp_path / "candidate_input_review.json",
        {
            "artifact": "candidate_input_review",
            "summary": {
                "status": "pass",
                "rows": 7,
                "issue_codes": {"candidate_file_empty": 1},
            },
        },
    )

    output = render_pilot_dashboard(
        output=tmp_path / "dashboard.html",
        local_pilot_path=local_pilot,
        candidate_queue_path=queue,
        candidate_gap_path=gap,
        assessment_path=assessment,
        input_review_path=input_review,
        preview_links={"종목 콘텐츠": "preview/index.html"},
    )

    html = output.read_text(encoding="utf-8")
    assert "TradingAgents Local Pilot Dashboard" in html
    assert "continue_with_constraints" in html
    assert "needs_more_candidates" in html
    assert "Ready candidates" in html
    assert "Input review" in html
    assert "pass / 7 rows" in html
    assert "9 / 20" in html
    assert "Shortfall" in html
    assert "11" in html
    assert "AAPL" in html
    assert "Apple Inc." in html
    assert "stock profile or saved report plus Toss/local market snapshot" in html
    assert "preview/index.html" in html
