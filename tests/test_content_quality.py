import json

import pytest

from tradingagents.content_quality import assess_content_snapshot, audit_content_snapshots
from tradingagents.content_snapshot import build_content_snapshot


@pytest.mark.unit
def test_content_snapshot_filters_common_report_metadata_variants():
    state = {
        "asset_type": "stock",
        "instrument_context": "Company: Example; Exchange: KSC.",
        "news_report": "\n".join([
            "보고서 작성일: 2026년 7월 9일",
            "대상 종목: 005930.KS",
            "실적 발표 이후 외국인 매도가 이어졌습니다.",
        ]),
        "fundamentals_report": "Executive Summary\n매출은 반도체와 모바일에서 나옵니다.",
        "risk_debate_state": {"judge_decision": "리스크는 환율입니다."},
    }

    content = build_content_snapshot(state, "005930.KS")

    why = next(card for card in content["cards"] if card["id"] == "why_moved")
    composition = next(card for card in content["cards"] if card["id"] == "composition")
    assert why["bullets"][0] == "실적 발표 이후 외국인 매도가 이어졌습니다."
    assert "보고서 작성일" not in " ".join(why["bullets"])
    assert "Executive Summary" not in " ".join(composition["bullets"])


@pytest.mark.unit
def test_assess_content_snapshot_flags_metadata_and_missing_market_data():
    content = {
        "artifact": "content_snapshot",
        "ticker": "005930.KS",
        "content_type": "stock",
        "cards": [
            {"id": "what_is_it", "status": "ready", "body": "보고서 작성일: 2026년 7월 9일"},
            {"id": "why_moved", "status": "ready", "body": "실적 발표 이후 움직였습니다."},
            {"id": "composition", "status": "ready", "body": "반도체와 모바일입니다."},
            {"id": "risk", "status": "ready", "body": "환율 리스크입니다."},
            {"id": "watch_next", "status": "ready", "body": "실적 발표를 봅니다."},
        ],
        "visuals": [{"id": "price_trend", "status": "needs_data"}],
        "publish_gate": {"status": "ready"},
    }

    audit = assess_content_snapshot(content)

    assert audit["status"] == "warn"
    codes = [issue["code"] for issue in audit["issues"]]
    assert "report_metadata_leak" in codes
    assert "missing_market_snapshot" in codes
    assert "price_trend_not_ready" in codes


@pytest.mark.unit
def test_audit_content_snapshots_summarizes_rows(tmp_path):
    content = {
        "artifact": "content_snapshot",
        "ticker": "AAPL",
        "content_type": "stock",
        "cards": [
            {"id": "what_is_it", "status": "ready", "body": "Apple입니다."},
            {"id": "why_moved", "status": "ready", "body": "실적 때문입니다."},
            {"id": "composition", "status": "ready", "body": "제품과 서비스입니다."},
            {"id": "risk", "status": "ready", "body": "환율입니다."},
            {"id": "watch_next", "status": "ready", "body": "다음 실적입니다."},
        ],
        "visuals": [{"id": "price_trend", "status": "ready"}, {"id": "volume_change", "status": "ready"}],
        "market_data": {"snapshot_file": "market.json"},
        "publish_gate": {"status": "ready"},
    }
    path = tmp_path / "content_snapshot.json"
    path.write_text(json.dumps(content), encoding="utf-8")

    payload = audit_content_snapshots([path])

    assert payload["summary"]["snapshots"] == 1
    assert payload["summary"]["pass_pct"] == 100.0


@pytest.mark.unit
def test_assess_content_snapshot_requires_etf_composition_data():
    content = {
        "artifact": "content_snapshot",
        "ticker": "DEMOETF",
        "content_type": "etf",
        "cards": [
            {"id": "what_is_it", "status": "ready", "body": "ETF입니다."},
            {"id": "why_moved", "status": "ready", "body": "구성 종목 영향입니다."},
            {"id": "composition", "status": "ready", "body": "상위 보유 종목입니다."},
            {"id": "risk", "status": "ready", "body": "집중도 리스크입니다."},
            {"id": "watch_next", "status": "ready", "body": "리밸런싱을 봅니다."},
        ],
        "composition_data": {"holdings": [{"name": "A", "weight_pct": 50}]},
        "visuals": [],
        "publish_gate": {"status": "ready"},
    }

    audit = assess_content_snapshot(content)

    assert audit["status"] == "fail"
    codes = [issue["code"] for issue in audit["issues"]]
    assert "etf_composition_data_missing" in codes


@pytest.mark.unit
def test_assess_content_snapshot_requires_theme_map_and_names():
    content = {
        "artifact": "content_snapshot",
        "ticker": "KR-AI-SEMI",
        "content_type": "theme",
        "cards": [
            {"id": "what_is_it", "status": "ready", "body": "테마입니다."},
            {"id": "why_moved", "status": "ready", "body": "AI 투자 때문입니다."},
            {"id": "composition", "status": "ready", "body": "밸류체인입니다."},
            {"id": "risk", "status": "ready", "body": "사이클 리스크입니다."},
            {"id": "watch_next", "status": "ready", "body": "수주를 봅니다."},
        ],
        "composition_data": {"value_chain": [{"stage": "메모리"}]},
        "visuals": [],
        "publish_gate": {"status": "ready"},
    }

    audit = assess_content_snapshot(content)

    codes = [issue["code"] for issue in audit["issues"]]
    assert audit["status"] == "fail"
    assert "theme_representative_names_missing" in codes
