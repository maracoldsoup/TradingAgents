"""Tests for the live dashboard (dashboard/events.py, dashboard/server.py)."""

from __future__ import annotations

import json

import pytest

from tradingagents.dashboard.events import DashboardEventTranslator


def _types(events):
    return [e["type"] for e in events]


def test_translator_emits_reports_once():
    tr = DashboardEventTranslator()
    chunk = {"market_report": "기술적 분석 결과", "news_report": ""}
    events = tr.translate(chunk)
    assert _types(events) == ["report"]
    assert events[0]["agent"] == "market"
    # 같은 내용 재수신 시 재발행 금지 (values 스트림은 상태를 반복 노출)
    assert tr.translate(chunk) == []


def test_translator_debate_deltas_are_incremental():
    tr = DashboardEventTranslator()
    first = {"investment_debate_state": {"bull_history": "Bull: 저평가 구간입니다."}}
    events = tr.translate(first)
    assert _types(events) == ["debate"]
    assert events[0]["speaker"] == "bull"

    grown = {
        "investment_debate_state": {
            "bull_history": "Bull: 저평가 구간입니다.\nBull: 수급도 개선 중입니다.",
            "bear_history": "Bear: 재료 소멸 위험이 있습니다.",
        }
    }
    events = tr.translate(grown)
    speakers = [(e["speaker"], e["content"]) for e in events]
    assert ("bull", "Bull: 수급도 개선 중입니다.") in speakers
    assert any(s == "bear" for s, _ in speakers)


def test_translator_final_event_carries_standard_rating():
    tr = DashboardEventTranslator()
    chunk = {"final_trade_decision": "**Rating**: Overweight\n\n비중 확대 권고"}
    events = tr.translate(chunk)
    final = [e for e in events if e["type"] == "final"]
    assert len(final) == 1
    assert final[0]["rating"] == "Overweight"
    assert final[0]["action"] == "Buy"
    assert final[0]["bias"] == "bullish"
    # 재발행 금지
    assert tr.translate(chunk) == []


def test_translator_telemetry_and_risk_and_trader():
    tr = DashboardEventTranslator()
    chunk = {
        "analyst_telemetry": {"market": {"seconds": 12.0, "tool_calls": 5}},
        "trader_investment_plan": "**Action**: Buy",
        "risk_debate_state": {"aggressive_history": "Aggressive: 비중 상단 제안"},
    }
    events = tr.translate(chunk)
    kinds = _types(events)
    assert "telemetry" in kinds and "trader" in kinds and "risk" in kinds


def test_sse_stream_end_to_end_with_fake_graph():
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from fastapi.testclient import TestClient

    from tradingagents.dashboard.server import create_app

    class FakeGraph:
        """propagate(on_chunk=...) 계약만 흉내내는 그래프 대역."""

        def propagate(self, ticker, trade_date, asset_type="stock", on_chunk=None):
            chunks = [
                {"market_report": "차트 요약"},
                {
                    "market_report": "차트 요약",
                    "investment_debate_state": {"bull_history": "Bull: 매수"},
                },
                {
                    "market_report": "차트 요약",
                    "final_trade_decision": "**Rating**: Hold\n관망",
                },
            ]
            for c in chunks:
                on_chunk(c)
            return {}, "HOLD"

    app = create_app(graph_factory=FakeGraph)
    client = TestClient(app)

    with client.stream("GET", "/api/stream?ticker=005930.KS") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        payloads = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                payloads.append(json.loads(line[len("data: "):]))

    kinds = [p["type"] for p in payloads]
    assert kinds[0] == "stage" and payloads[0]["stage"] == "start"
    assert "report" in kinds and "debate" in kinds and "final" in kinds
    assert kinds[-1] == "stage" and payloads[-1]["stage"] == "done"
    assert payloads[-1]["decision"] == "HOLD"


def test_sse_stream_surfaces_graph_error():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from tradingagents.dashboard.server import create_app

    class BoomGraph:
        def propagate(self, *a, **k):
            raise ValueError("vendor exploded")

    app = create_app(graph_factory=BoomGraph)
    client = TestClient(app)
    with client.stream("GET", "/api/stream?ticker=NVDA") as resp:
        payloads = [
            json.loads(line[len("data: "):])
            for line in resp.iter_lines()
            if line.startswith("data: ")
        ]
    errors = [p for p in payloads if p["type"] == "error"]
    assert errors and "vendor exploded" in errors[0]["message"]
