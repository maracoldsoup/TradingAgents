import json

import pytest

from tradingagents.candidate_gap import analyze_candidate_gap, write_candidate_gap


def _queue_payload(ready_rows=9):
    rows = [
        {"ticker": "005930.KS", "content_type": "stock", "market": "KR", "status": "ready_for_local_pilot"},
        {"ticker": "068270.KS", "content_type": "stock", "market": "KR", "status": "ready_for_local_pilot"},
        {"ticker": "207940.KS", "content_type": "stock", "market": "KR", "status": "ready_for_local_pilot"},
        {"ticker": "DEMO2BAT.KS", "content_type": "etf", "market": "KR", "status": "ready_for_local_pilot"},
        {"ticker": "KR-AI-SEMI", "content_type": "theme", "market": "KR", "status": "ready_for_local_pilot"},
        {"ticker": "KR-AI-SEMI-CSV", "content_type": "theme", "market": "KR", "status": "ready_for_local_pilot"},
        {"ticker": "AAPL", "content_type": "stock", "market": "US", "status": "ready_for_local_pilot"},
        {"ticker": "DEMOIMPORT", "content_type": "etf", "market": "US", "status": "ready_for_local_pilot"},
        {"ticker": "DEMOUSAI", "content_type": "etf", "market": "US", "status": "ready_for_local_pilot"},
    ][:ready_rows]
    return {
        "schema_version": 1,
        "artifact": "candidate_queue",
        "target_candidates": 20,
        "summary": {"ready_for_local_pilot": len(rows)},
        "rows": rows,
    }


@pytest.mark.unit
def test_analyze_candidate_gap_builds_actionable_shortfall():
    payload = analyze_candidate_gap(_queue_payload(), target_candidates=20)

    assert payload["artifact"] == "candidate_gap"
    assert payload["status"] == "needs_inputs"
    assert payload["summary"]["ready_for_local_pilot"] == 9
    assert payload["summary"]["ready_shortfall"] == 11
    assert payload["type_gaps"]["stock"]["add_at_least"] == 4
    assert payload["type_gaps"]["etf"]["add_at_least"] == 1
    assert payload["type_gaps"]["theme"]["add_at_least"] == 2
    assert payload["market_gaps"]["KR"]["add_at_least"] == 4
    assert payload["market_gaps"]["US"]["add_at_least"] == 3
    assert len(payload["slot_plan"]) == 11
    assert any("Add 11 more ready local candidates" in action for action in payload["actions"])


@pytest.mark.unit
def test_analyze_candidate_gap_tracks_existing_blocked_rows():
    queue = _queue_payload()
    queue["rows"].append({
        "ticker": "NVDA",
        "content_type": "stock",
        "market": "US",
        "status": "needs_seed_data",
        "missing_inputs": ["saved_report_or_profile", "market_snapshot"],
    })

    payload = analyze_candidate_gap(queue, target_candidates=20)

    assert payload["summary"]["blocked_existing_candidates"] == 1
    assert payload["summary"]["missing_inputs"]["saved_report_or_profile"] == 1
    assert payload["summary"]["missing_inputs"]["market_snapshot"] == 1
    assert any("Complete market_snapshot" in action for action in payload["actions"])


@pytest.mark.unit
def test_write_candidate_gap_outputs_json_and_markdown(tmp_path):
    queue = tmp_path / "candidate_queue.json"
    queue.write_text(json.dumps(_queue_payload(), ensure_ascii=False), encoding="utf-8")

    payload = write_candidate_gap(candidate_queue_path=queue, output_dir=tmp_path / "out")

    assert payload["summary"]["ready_shortfall"] == 11
    assert (tmp_path / "out" / "candidate_gap.json").exists()
    markdown = (tmp_path / "out" / "candidate_gap.md").read_text(encoding="utf-8")
    assert "# Candidate Gap" in markdown
    assert "ready_shortfall: 11" in markdown
